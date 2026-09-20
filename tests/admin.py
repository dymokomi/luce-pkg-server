#!/usr/bin/env python3
"""Production operator CLI against a disposable native registry."""
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

admin, registry = [Path(value).resolve() for value in sys.argv[1:3]]


def invoke(arguments, environment, success=True, timeout=90):
    result = subprocess.run([str(admin), *map(str, arguments)], env=environment,
                            capture_output=True, timeout=timeout)
    assert result.returncode >= 0, result.stderr
    assert (result.returncode == 0) == success, result.stderr
    return result


def request(port, method, path, payload=None):
    body = b'' if payload is None else json.dumps(payload).encode()
    headers = {} if payload is None else {'Content-Type': 'application/json'}
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=90)
    try:
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


with tempfile.TemporaryDirectory(prefix='luce-pkg-admin-', dir='/tmp') as temporary:
    root = Path(temporary)
    database = root / 'registry.db'
    socket_path = Path(str(database) + '.sock')
    environment = dict(os.environ, LUCE_REGISTRY_STORE_TOKEN='admin-integration-token',
                       LUCE_REGISTRY_ORIGIN='https://pkg.luciaos.com')
    first_token = invoke(['token'], environment).stdout.strip()
    second_token = invoke(['token'], environment).stdout.strip()
    assert len(first_token) == 64 and first_token != second_token
    assert all(value in b'0123456789abcdef' for value in first_token + second_token)
    missing = dict(environment)
    missing.pop('LUCE_REGISTRY_STORE_TOKEN')
    invoke(['init', database], missing, False)
    assert not database.exists()
    assert invoke(['init', database], environment).stdout == b'initialized\n'
    # Initialization and offline checkpointing are repeatable.
    assert invoke(['init', database], environment).stdout == b'initialized\n'
    assert invoke(['checkpoint', database], environment).stdout.startswith(b'checkpoint ')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    with (root / 'registry.log').open('w+') as log:
        process = subprocess.Popen([str(registry), str(database), str(port)], env=environment,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                assert process.poll() is None, 'registry exited'
                try:
                    if request(port, 'GET', '/health') == (200, b'ok'):
                        break
                except OSError:
                    time.sleep(.05)
            else:
                raise AssertionError('registry startup timeout')
            wrong = dict(environment, LUCE_REGISTRY_STORE_TOKEN='wrong-token')
            invoke(['invite', socket_path], wrong, False)
            result = invoke(['invite', socket_path], environment)
            code = result.stdout.strip()
            assert len(code) == 32 and all(value in b'0123456789abcdef' for value in code)
            assert request(port, 'POST', '/v1/invites/redeem', {
                'code': code.decode(), 'name': 'operator_test', 'password': 'production-profile-test'
            }) == (201, b'registered')
            assert request(port, 'POST', '/v1/invites/redeem', {
                'code': code.decode(), 'name': 'replay', 'password': 'production-profile-test'
            })[0] == 400
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise
            if process.returncode != 0:
                log.seek(0)
                raise AssertionError(log.read())
    assert invoke(['checkpoint', database], environment).stdout.startswith(b'checkpoint ')
    assert not socket_path.exists()

print('PASS operator init, live invitation, one-use redemption and offline checkpoint')
