#!/usr/bin/env python3
"""Migration round trip: a database in the former layout (objects inside Prism, inline
and chunked) is migrated to object files; the migration is idempotent and resumable;
the migrated registry serves a fresh clone, keeps its account, and publishes a release
built from migrated objects."""
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time

registry, admin, legacy = [Path(value).resolve() for value in sys.argv[1:4]]
TOKEN = 'integration-store-token'


def request(port, method, path, value=None, headers=None):
    payload = json.dumps(value).encode() if value is not None else b''
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=300)
    try:
        connection.request(method, path, payload, headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def size(path):
    return sum(file.stat().st_size for file in Path(path).rglob('*') if file.is_file())


with tempfile.TemporaryDirectory(prefix='registry-migration-', dir='/tmp') as temporary:
    root = Path(temporary)
    git_env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0',
                   GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.test',
                   GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.test')
    work = root / 'work'
    def git(*args, cwd=work, input=None):
        result = subprocess.run(['git', '-C', str(cwd), *args], env=git_env, input=input, capture_output=True, timeout=300)
        assert result.returncode == 0, (args, result.stderr)
        return result.stdout
    work.mkdir()
    git('init', '-q', '-b', 'main', '--object-format=sha1')
    large = os.urandom(3 * 1048576 + 12345)  # chunked in the former layout
    (work / 'large.bin').write_bytes(large)
    (work / 'README.md').write_text('# legacy\n')
    (work / 'package.prisma').write_text('#prisma 4.0\ndef package "legacy" {\n    str owner = "testadmin"\n'
        '    str version = "1.0.0"\n    str kind = "package"\n    str language = "luce-base"\n'
        '    str description = "Migration fixture"\n    str readme = "README.md"\n}\n')
    git('add', '.')
    git('commit', '-qm', 'first')
    (work / 'src').mkdir()
    (work / 'src/main.lucb').write_text('pub func main() -> i32:\n    return 0\n')
    git('add', '.')
    git('commit', '-qm', 'second')
    head = git('rev-parse', 'HEAD').strip().decode()
    pack = root / 'legacy.pack'
    pack.write_bytes(git('pack-objects', '--revs', '--stdout', input=b'main\n'))
    count = int(git('rev-list', '--objects', '--all').decode().count('\n'))

    source = root / 'old' / 'registry.db'
    source.parent.mkdir()
    environment = dict(os.environ, LUCE_REGISTRY_STORE_TOKEN=TOKEN, LUCE_REGISTRY_ORIGIN='https://pkg.luciaos.com',
                       LUCE_REGISTRY_SITE=str(root / 'site'))
    output = subprocess.run([str(legacy), str(source), str(pack), head], env=environment,
                            capture_output=True, text=True, timeout=120)
    assert output.returncode == 0 and output.stdout.strip() == f'legacy {count} objects', (output.stdout, output.stderr)
    before = size(source.parent)
    assert before > 3 * 1048576, before

    target = root / 'new' / 'registry.db'
    target.parent.mkdir()
    def migrate(expect_written, expect_removed=0):
        result = subprocess.run([str(admin), 'migrate', str(source), str(target)], env=environment,
                                capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, result.stderr
        found = re.fullmatch(r'migrated (\d+) elements, (\d+) objects \((\d+) bytes\), wrote (\d+) object files, removed (\d+)\n', result.stdout)
        assert found, result.stdout
        objects, written, removed = int(found[2]), int(found[4]), int(found[5])
        assert objects == count and written == expect_written and removed == expect_removed, result.stdout
        return result.stdout
    print('MIGRATE', migrate(count), end='', flush=True)
    objects = Path(str(target) + '.objects')
    files = [path for path in objects.rglob('*') if path.is_file()]
    assert len(files) == count and not any(path.name.startswith('.luce') for path in files)
    database_bytes = size(target.parent) - size(objects)
    assert database_bytes < 1048576 and database_bytes * 4 < before, (database_bytes, before)
    print(f'PASS migration moves {count} objects to files; database {before} -> {database_bytes} bytes', flush=True)
    # Idempotent: a second run writes nothing. Resumable: a lost object file is rewritten
    # from the source, and a missing source must not be required for the rest.
    migrate(0)
    files[0].unlink()
    migrate(1)
    for arguments in (['migrate', str(source), str(source)], ['migrate', str(root / 'absent.db'), str(target)]):
        assert subprocess.run([str(admin), *arguments], env=environment, capture_output=True, timeout=60).returncode != 0
    print('PASS migration is idempotent and resumes a lost object file', flush=True)

    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    with (root / 'registry.log').open('w+') as log:
        process = subprocess.Popen([str(registry), str(target), str(port)], env=environment,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 30
            while True:
                assert process.poll() is None, 'registry exited'
                try:
                    if request(port, 'GET', '/health') == (200, b'ok'):
                        break
                except OSError:
                    pass
                assert time.monotonic() < deadline, 'registry startup timeout'
                time.sleep(.05)
            endpoint = f'http://127.0.0.1:{port}/git/testadmin/legacy'
            clone = root / 'clone'
            subprocess.run(['git', 'clone', '-q', endpoint, str(clone)], env=git_env, check=True, capture_output=True, timeout=300)
            git('fsck', '--strict', cwd=clone)
            assert (clone / 'large.bin').read_bytes() == large and git('rev-parse', 'HEAD', cwd=clone).strip().decode() == head
            print('PASS a fresh clone of a migrated repository is byte for byte', flush=True)
            # The account moved too: log in, and publish a release from migrated objects.
            status, session = request(port, 'POST', '/v1/sessions', {'name': 'testadmin', 'password': 'fixture-password'})
            assert status == 200, status
            status, credential = request(port, 'POST', '/v1/credentials',
                                         {'scope': 'git:write', 'repository': 'legacy', 'lifetime_seconds': 3600},
                                         {'Authorization': 'Bearer ' + session.decode()})
            assert status == 201
            askpass = root / 'askpass.sh'
            askpass.write_text('#!/bin/sh\ncase "$1" in\n  *Username*) echo testadmin ;;\n  *) printf "%s\\n" "$T" ;;\nesac\n')
            askpass.chmod(0o700)
            git_env.update(GIT_ASKPASS=str(askpass), T=credential.decode())
            git('tag', '-a', 'v1.0.0', '-m', 'Released after migration.')
            git('remote', 'add', 'origin', endpoint)
            git('push', 'origin', 'v1.0.0')
            released = root / 'site/testadmin/legacy/1.0.0.pack'
            unpacked = root / 'unpacked'
            subprocess.run(['git', 'init', '-q', str(unpacked)], env=git_env, check=True, timeout=30)
            git('unpack-objects', cwd=unpacked, input=released.read_bytes())
            assert git('cat-file', 'blob', f'{head}:large.bin', cwd=unpacked) == large
            print('PASS the migrated account logs in and publishes a release built from migrated objects', flush=True)
        finally:
            if sys.exc_info()[0] is not None:
                log.flush()
                log.seek(0)
                print('REGISTRY LOG:\n' + log.read(), file=sys.stderr, flush=True)
            process.terminate()
            process.wait(timeout=30)
        assert process.returncode == 0, process.returncode
