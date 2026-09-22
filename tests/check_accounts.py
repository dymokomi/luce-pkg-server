#!/usr/bin/env python3
"""Independent HTTP tests; short private paths and disposable accounts only."""
import concurrent.futures
import base64
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import git_http

binary, fixture = [Path(arg).resolve() for arg in sys.argv[1:3]]
registration_client = Path(sys.argv[4]).resolve() if len(sys.argv) == 5 else None

def request(port, method, path, value=None, headers=None, include_headers=False):
    payload = json.dumps(value).encode() if value is not None else b''
    timeout = float(os.environ.get('LUCE_TEST_HTTP_TIMEOUT', '10'))
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    try:
        connection.request(method, path, payload, headers or {})
        response = connection.getresponse()
        body = response.read()
        if include_headers:
            return response.status, body, dict(response.getheaders())
        return response.status, body
    finally:
        connection.close()

def issue_credential(port, session_headers, scope, repository, lifetime=3600):
    status, token = request(port, 'POST', '/v1/credentials',
                            {'scope': scope, 'repository': repository, 'lifetime_seconds': lifetime},
                            session_headers)
    assert status == 201 and len(token) == 64 and all(c in b'0123456789abcdef' for c in token), (status, token)
    return token, {'Authorization': 'Bearer ' + token.decode()}

def git_headers(name, token):
    return {'Authorization': 'Basic ' + base64.b64encode(name.encode() + b':' + token).decode()}

with tempfile.TemporaryDirectory(prefix='registry-auth-', dir='/tmp') as temporary:
    root = Path(temporary)
    database = root / 'registry.db'
    code, race_code = subprocess.check_output([str(fixture), str(database)], text=True, timeout=30).splitlines()
    assert len(code) == len(race_code) == 32
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    env = dict(os.environ, LUCE_REGISTRY_STORE_TOKEN='integration-store-token',
               LUCE_REGISTRY_ORIGIN='https://pkg.luciaos.com', LUCE_REGISTRY_SITE=str(root / 'site'))
    with (root / 'server.log').open('w+') as log:
        process = subprocess.Popen([str(binary), str(database), str(port)], env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 20
            while True:
                if process.poll() is not None:
                    log.seek(0)
                    raise AssertionError(log.read())
                try:
                    if request(port, 'GET', '/health') == (200, b'ok'):
                        break
                except OSError:
                    pass
                assert time.monotonic() < deadline, 'registry startup timeout'
                time.sleep(.05)
            assert request(port, 'GET', '/v1/identity', headers={'X-Forwarded-For': '127.0.0.1'})[0] == 401
            for token in ('Bearer secret', 'Bearer ../users/testadmin', 'Bearer ' + 'a' * 3000):
                assert request(port, 'GET', '/v1/identity', headers={'Authorization': token})[0] == 401
            # Unknown invitations cannot create users; duplicate account must not burn a valid invite.
            assert request(port, 'POST', '/v1/invites/redeem', {'code': '0' * 32, 'name': 'testuser', 'password': 'fixture-pass'})[0] == 400
            assert request(port, 'POST', '/v1/invites/redeem', {'code': code, 'name': 'testadmin', 'password': 'changed'})[0] == 409
            if registration_client is None:
                assert request(port, 'POST', '/v1/invites/redeem', {'code': code, 'name': 'testuser', 'password': 'fixture-pass'}) == (201, b'registered')
            else:
                registered = subprocess.run([str(registration_client), 'register', f'http://127.0.0.1:{port}',
                                             'testuser', '--secrets-stdin'], input=code.encode() + b'\nfixture-pass\n',
                                            capture_output=True, timeout=60)
                assert registered.returncode == 0, registered.stderr
                assert code.encode() not in registered.stdout + registered.stderr
                assert b'fixture-pass' not in registered.stdout + registered.stderr
                print('PASS luc invited registration against native registry', flush=True)
            assert request(port, 'POST', '/v1/invites/redeem', {'code': code, 'name': 'other', 'password': 'fixture-pass'})[0] == 400
            def register(name):
                return request(port, 'POST', '/v1/invites/redeem', {'code': race_code, 'name': name, 'password': 'race-pass'})[0]
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(register, ['racerone', 'racertwo']))
            assert statuses.count(201) == 1 and all(status in (201, 400, 409) for status in statuses), statuses
            # Exercise the HTTP admission gate with syntactically valid JSON
            # that authentication rejects before Argon2. Valid nonexistent
            # accounts intentionally perform password work and can span a full
            # 60-second window in unoptimized generated-C builds.
            registration_attempts = [
                request(port, 'POST', '/v1/invites/redeem',
                        {'code': f'{index + 1000:032x}', 'name': f'Invalid{index}', 'password': 'wrong'})
                for index in range(32)
            ]
            assert all(status in (400, 429) for status, _ in registration_attempts), registration_attempts
            assert any(value == (429, b'rate limited') for value in registration_attempts), registration_attempts
            status, body, response_headers = request(
                port, 'POST', '/v1/invites/redeem',
                {'code': code, 'name': 'limited', 'password': 'wrong'},
                include_headers=True)
            assert (status, body) == (429, b'rate limited')
            assert response_headers.get('Retry-After') == '60', response_headers
            assert response_headers.get('Cache-Control') == 'no-store', response_headers
            # Registration and login use independent process-wide gates.
            assert request(port, 'POST', '/v1/sessions', {'name': 'testuser', 'password': 'wrong'})[0] == 401
            status, token = request(port, 'POST', '/v1/sessions', {'name': 'testuser', 'password': 'fixture-pass'})
            assert status == 200 and len(token) == 32, (status, token)
            headers = {'Authorization': 'Bearer ' + token.decode(), 'X-Forwarded-For': '8.8.8.8'}
            for value in ({}, {'scope': 'git:admin', 'repository': 'demo', 'lifetime_seconds': 60},
                          {'scope': 'git:read', 'repository': '../escape', 'lifetime_seconds': 60},
                          {'scope': 'git:read', 'repository': 'demo', 'lifetime_seconds': 59},
                          {'scope': 'git:read', 'repository': 'demo', 'lifetime_seconds': 7776001},
                          {'scope': 'git:read', 'repository': 'demo', 'lifetime_seconds': '3600'},
                          {'scope': 'git:read', 'repository': 'demo', 'lifetime_seconds': 60, 'extra': 1}):
                assert request(port, 'POST', '/v1/credentials', value, headers)[0] == 400, value
            assert request(port, 'POST', '/v1/credentials',
                           {'scope': 'git:read', 'repository': 'demo', 'lifetime_seconds': 60})[0] == 401
            endpoint = '/v1/repositories'
            assert request(port, 'POST', endpoint, {'name': 'demo'})[0] == 401
            assert request(port, 'POST', endpoint, {'name': 'demo'},
                           {'X-Forwarded-User': 'testuser'})[0] == 401
            for value in ({}, [], {'name': 3}, {'name': '../escape'}, {'name': 'UPPER'},
                          {'name': 'demo', 'owner': 'testadmin'}, {'name': 'x' * 65}):
                assert request(port, 'POST', endpoint, value, headers)[0] == 400, value
            assert request(port, 'POST', endpoint, {'name': 'demo'}, headers) == (201, b'created')
            assert request(port, 'POST', endpoint, {'name': 'demo'}, headers)[0] == 409
            def create_repository(_):
                return request(port, 'POST', endpoint, {'name': 'parallel'}, headers)[0]
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                creations = list(pool.map(create_repository, range(16)))
            assert creations.count(201) == 1 and creations.count(409) == 15, creations
            admin_status, admin_token = request(port, 'POST', '/v1/sessions',
                                                {'name': 'testadmin', 'password': 'fixture-password'})
            assert admin_status == 200
            admin_headers = {'Authorization': 'Bearer ' + admin_token.decode()}
            assert request(port, 'POST', endpoint, {'name': 'demo'}, admin_headers)[0] == 201
            git_token, _ = issue_credential(port, headers, 'git:write', 'git-wire')
            temporary_git, _ = issue_credential(port, headers, 'git:read', 'git-wire', 60)
            assert request(port, 'POST', '/v1/credentials/revoke', {'token': temporary_git.decode()}, admin_headers)[0] == 404
            assert request(port, 'POST', '/v1/credentials/revoke', {'token': temporary_git.decode()}, headers) == (200, b'revoked')
            git_commit = git_http.check(port, headers, git_token, root, request)
            def identity(_):
                return request(port, 'GET', '/v1/identity', headers=headers)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                assert all(value == (200, b'testuser') for value in pool.map(identity, range(32)))
            assert request(port, 'POST', '/v1/sessions/revoke', headers=headers) == (200, b'revoked')
            assert request(port, 'GET', '/v1/identity', headers=headers)[0] == 401
            assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-receive-pack', headers=headers)[0] == 401
            assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-receive-pack',
                           headers=git_headers('testuser', git_token))[0] == 200
            assert request(port, 'POST', endpoint, {'name': 'revoked'}, headers)[0] == 401
            assert request(port, 'POST', '/v1/sessions', {'name': 'testadmin', 'password': 'fixture-password'})[0] == 200
            # Syntactically valid unauthenticated requests consume a process-wide
            # fixed window before semantic validation or password KDF work.
            # Malformed bodies do not consume it.
            attempts = [request(port, 'POST', '/v1/sessions',
                                {'name': f'Invalid{index}', 'password': 'wrong'})
                        for index in range(32)]
            assert all(status in (401, 429) for status, _ in attempts), attempts
            assert any(value == (429, b'rate limited') for value in attempts), attempts
            status, body, response_headers = request(
                port, 'POST', '/v1/sessions',
                {'name': 'testadmin', 'password': 'fixture-password'},
                include_headers=True)
            assert (status, body) == (429, b'rate limited')
            assert response_headers.get('Retry-After') == '60', response_headers
            assert response_headers.get('Cache-Control') == 'no-store', response_headers
        finally:
            if sys.exc_info()[0] is not None or process.poll() is not None:
                log.flush()
                log.seek(0)
                print('REGISTRY FAILURE LOG:\n' + log.read(), file=sys.stderr, flush=True)
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise AssertionError('registry failed to shut down')
        assert process.returncode == 0, process.returncode
        # Same persistent store, new owner and HTTP workers. No reseeding.
        process = subprocess.Popen([str(binary), str(database), str(port)], env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 20
            while True:
                assert process.poll() is None, 'registry restart failed'
                try:
                    if request(port, 'GET', '/health') == (200, b'ok'):
                        break
                except OSError:
                    pass
                assert time.monotonic() < deadline, 'registry restart timeout'
                time.sleep(.05)
            assert request(port, 'GET', '/v1/identity', headers=headers)[0] == 401
            assert request(port, 'POST', '/v1/invites/redeem', {'code': code, 'name': 'later', 'password': 'fixture-pass'})[0] == 400
            status, restored = request(port, 'POST', '/v1/sessions', {'name': 'testuser', 'password': 'fixture-pass'})
            assert status == 200 and len(restored) == 32
            assert request(port, 'GET', '/v1/identity', headers={'Authorization': 'Bearer ' + restored.decode()}) == (200, b'testuser')
            restored_headers = {'Authorization': 'Bearer ' + restored.decode()}
            status, advertisement = request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-receive-pack', headers=git_headers('testuser', git_token))
            assert status == 200 and git_commit + b' refs/heads/main' in advertisement
            assert request(port, 'POST', '/v1/repositories', {'name': 'demo'}, restored_headers)[0] == 409
            assert request(port, 'POST', '/v1/repositories', {'name': 'parallel'}, restored_headers)[0] == 409
            assert request(port, 'POST', '/v1/repositories', {'name': 'after-restart'}, restored_headers)[0] == 201
        finally:
            if sys.exc_info()[0] is not None or process.poll() is not None:
                log.flush()
                log.seek(0)
                print('REGISTRY RESTART FAILURE LOG:\n' + log.read(), file=sys.stderr, flush=True)
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise AssertionError('restarted registry failed to shut down')
        assert process.returncode == 0, process.returncode
        # Missing origin disables enrollment, never derives it from HTTP headers.
        env.pop('LUCE_REGISTRY_ORIGIN')
        process = subprocess.Popen([str(binary), str(database), str(port)], env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 20
            while True:
                assert process.poll() is None, 'unconfigured registry failed'
                try:
                    if request(port, 'GET', '/health') == (200, b'ok'):
                        break
                except OSError:
                    pass
                assert time.monotonic() < deadline, 'unconfigured registry timeout'
                time.sleep(.05)
            # Without a configured origin the registry still serves health and refuses to publish.
            assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-upload-pack')[0] == 200
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise AssertionError('unconfigured registry failed to shut down')
        assert process.returncode == 0, process.returncode
    for bad_origin in ('bad origin', 'a' * 256):
        result = subprocess.run([str(binary), str(root / 'unused.db'), '0'],
                                env=dict(env, LUCE_REGISTRY_ORIGIN=bad_origin),
                                capture_output=True, timeout=10)
        assert result.returncode != 0
        assert not (root / 'unused.db').exists()
print('PASS real registry accounts: invited registration, login, parallel identity, revoke, proxy spoof rejection')
print('PASS restart preserves users, invitation consumption and session revocation')
print('PASS authenticated repository creation, namespace isolation, races, revocation and restart')
