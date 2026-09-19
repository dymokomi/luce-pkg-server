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

binary, fixture = [Path(arg).resolve() for arg in sys.argv[1:]]

def request(port, method, path, value=None, headers=None):
    payload = json.dumps(value).encode() if value is not None else b''
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
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
    env = dict(os.environ, LUCE_REGISTRY_STORE_TOKEN='integration-store-token')
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
            assert request(port, 'POST', '/v1/invites/redeem', {'code': code, 'name': 'testuser', 'password': 'fixture-pass'}) == (201, b'registered')
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
            def identity(_):
                return request(port, 'GET', '/v1/identity', headers=headers)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                assert all(value == (200, b'testuser') for value in pool.map(identity, range(32)))
            assert request(port, 'POST', '/v1/sessions/revoke', headers=headers) == (200, b'revoked')
            assert request(port, 'GET', '/v1/identity', headers=headers)[0] == 401
            assert request(port, 'POST', '/v1/sessions', {'name': 'testadmin', 'password': 'fixture-password'})[0] == 200
        finally:
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
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise AssertionError('restarted registry failed to shut down')
        assert process.returncode == 0, process.returncode
print('PASS real registry accounts: invited registration, login, parallel identity, revoke, proxy spoof rejection')
print('PASS restart preserves users, invitation consumption and session revocation')
