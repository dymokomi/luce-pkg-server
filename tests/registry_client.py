"""Shared by the Git-level registry tests: HTTP requests, the registry process, and a
stock Git client that creates repositories and pushes releases as `testadmin`."""
import http.client
import json
import os
import socket
import subprocess
import time


def request(port, method, path, value=None, headers=None, raw=None):
    payload = raw if raw is not None else json.dumps(value).encode() if value is not None else b''
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=300)
    try:
        connection.request(method, path, payload, headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def start(registry, database, port, environment, log):
    process = subprocess.Popen([str(registry), str(database), str(port)], env=environment,
                               stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 30
    while True:
        assert process.poll() is None, 'registry exited'
        try:
            if request(port, 'GET', '/health') == (200, b'ok'):
                return process
        except OSError:
            pass
        assert time.monotonic() < deadline, 'registry startup timeout'
        time.sleep(.05)


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise AssertionError('registry failed to shut down')
    assert process.returncode == 0, process.returncode


class Client:
    """A stock Git client pushing as `owner` with one git:write credential per repository."""

    def __init__(self, root, port, session):
        self.root, self.port, self.session = root, port, session
        self.askpass = root / 'askpass.sh'
        self.askpass.write_text('#!/bin/sh\ncase "$1" in\n  *Username*) printf "%s\\n" "$LUCE_GIT_USERNAME" ;;\n'
                                '  *Password*) printf "%s\\n" "$LUCE_GIT_TOKEN" ;;\n  *) exit 1 ;;\nesac\n')
        self.askpass.chmod(0o700)

    def environment(self, repository):
        status, token = request(self.port, 'POST', '/v1/credentials',
                                {'scope': 'git:write', 'repository': repository, 'lifetime_seconds': 3600},
                                self.session)
        assert status == 201, (status, token)
        return dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0',
                    GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.test',
                    GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.test',
                    GIT_ASKPASS=str(self.askpass), LUCE_GIT_USERNAME='testadmin', LUCE_GIT_TOKEN=token.decode())

    def endpoint(self, repository):
        return f'http://127.0.0.1:{self.port}/git/testadmin/{repository}'

    def repository(self, name, files, version=None, extra=''):
        """Create `name` on the registry and a local repository holding `files`; with a
        `version`, a package.prisma (plus `extra` definition lines) and an annotated tag."""
        assert request(self.port, 'POST', '/v1/repositories', {'name': name}, self.session)[0] == 201
        environment = self.environment(name)
        work = self.root / name
        work.mkdir()
        def git(*args):
            result = subprocess.run(['git', '-C', str(work), *args], env=environment, capture_output=True, timeout=600)
            assert result.returncode == 0, (args, result.stderr)
        git('init', '-q', '-b', 'main', '--object-format=sha1')
        for relative, content in files.items():
            (work / relative).write_bytes(content)
        if version:
            (work / 'package.prisma').write_text(
                f'#prisma 4.0\ndef package "{name}" {{\n    str owner = "testadmin"\n    str version = "{version}"\n'
                '    str kind = "package"\n    str language = "luce-base"\n    str description = "Storage fixture"\n'
                f'{extra}}}\n')
        git('add', '.')
        git('commit', '-qm', f'{name} fixture')
        git('remote', 'add', 'origin', self.endpoint(name))
        if version: git('tag', '-a', f'v{version}', '-m', f'{name} {version}')
        return work, environment

    def push(self, work, environment, *refs):
        started = time.monotonic()
        result = subprocess.run(['git', '-C', str(work), 'push', '--porcelain', 'origin', *refs],
                                env=environment, capture_output=True, timeout=600)
        return result.returncode, result.stderr, time.monotonic() - started

    def clone(self, name, destination):
        subprocess.run(['git', 'clone', '-q', self.endpoint(name), str(destination)], check=True,
                       capture_output=True, timeout=600, env=dict(os.environ, GIT_TERMINAL_PROMPT='0'))
        subprocess.run(['git', '-C', str(destination), 'fsck', '--strict'], check=True, capture_output=True, timeout=600)


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]
