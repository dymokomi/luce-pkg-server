#!/usr/bin/env python3
"""Independent HTTP tests; short private paths and disposable accounts only."""
import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import object_http
import git_http
import key_http
import release_http

binary, fixture, client = [Path(arg).resolve() for arg in sys.argv[1:4]]
registration_client = Path(sys.argv[4]).resolve() if len(sys.argv) == 5 else None

def request(port, method, path, value=None, headers=None):
    payload = json.dumps(value).encode() if value is not None else b''
    timeout = float(os.environ.get('LUCE_TEST_HTTP_TIMEOUT', '10'))
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    try:
        connection.request(method, path, payload, headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()

with tempfile.TemporaryDirectory(prefix='registry-auth-', dir='/tmp') as temporary:
    root = Path(temporary)
    database = root / 'registry.db'
    code, race_code = subprocess.check_output([str(fixture), str(database)], text=True, timeout=30).splitlines()
    assert len(code) == len(race_code) == 32
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    env = dict(os.environ, LUCE_REGISTRY_STORE_TOKEN='integration-store-token',
               LUCE_REGISTRY_ORIGIN=key_http.ORIGIN)
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
            assert request(port, 'POST', '/v1/sessions', {'name': 'testuser', 'password': 'wrong'})[0] == 401
            status, token = request(port, 'POST', '/v1/sessions', {'name': 'testuser', 'password': 'fixture-pass'})
            assert status == 200 and len(token) == 32, (status, token)
            headers = {'Authorization': 'Bearer ' + token.decode(), 'X-Forwarded-For': '8.8.8.8'}
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
            enrolled_key = key_http.check(port, headers, admin_headers, fixture)
            assert request(port, 'POST', endpoint, {'name': 'demo'}, admin_headers)[0] == 201
            object_path, object_bytes = object_http.check(port, headers, admin_headers)
            git_commit = git_http.check(port, headers, root, request)
            release_expected, large_release_expected = release_http.check(port, headers, admin_headers, root, fixture, git_commit)
            subprocess.run([str(client), str(port)], check=True, timeout=120)
            def identity(_):
                return request(port, 'GET', '/v1/identity', headers=headers)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                assert all(value == (200, b'testuser') for value in pool.map(identity, range(32)))
            assert request(port, 'POST', '/v1/sessions/revoke', headers=headers) == (200, b'revoked')
            assert request(port, 'GET', '/v1/identity', headers=headers)[0] == 401
            assert request(port, 'POST', key_http.CHALLENGE, headers=headers)[0] == 401
            assert request(port, 'GET', key_http.ENROLL, headers=headers)[0] == 401
            assert request(port, 'GET', release_http.ROOT + '/1.2.3/source', headers=headers)[0] == 401
            assert request(port, 'POST', release_http.ROOT, headers=headers)[0] == 401
            assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-receive-pack', headers=headers)[0] == 401
            assert request(port, 'POST', endpoint, {'name': 'revoked'}, headers)[0] == 401
            assert object_http.transfer(port, 'GET', object_path, headers=headers)[0] == 401
            assert object_http.transfer(port, 'PUT', object_path, b'', headers)[0] == 401
            assert request(port, 'POST', '/v1/sessions', {'name': 'testadmin', 'password': 'fixture-password'})[0] == 200
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
            key_http.persisted(port, restored_headers, enrolled_key)
            release_http.persisted(port, restored_headers, release_expected)
            release_http.persisted(port, restored_headers, large_release_expected, '1.2.5')
            assert release_http.catalog(request(port, 'GET', '/v1/releases/testuser/git-wire', headers=restored_headers)[1]) == ['1.2.5', '1.2.4', '1.2.3']
            status, advertisement = request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-receive-pack', headers=restored_headers)
            assert status == 200 and git_commit + b' refs/heads/main' in advertisement
            subprocess.run([str(client), str(port)], check=True, timeout=120)
            assert object_http.transfer(port, 'GET', object_path, headers=restored_headers) == (200, object_bytes)
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
            for endpoint in (key_http.CHALLENGE, key_http.ENROLL):
                assert request(port, 'POST', endpoint)[0] == 401
                assert request(port, 'POST', endpoint, headers=restored_headers)[0] == 503
            assert request(port, 'POST', release_http.ROOT, headers=restored_headers)[0] == 503
            assert request(port, 'GET', release_http.ROOT + '/1.2.3/source', headers=restored_headers)[0] == 503
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
