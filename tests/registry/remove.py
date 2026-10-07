#!/usr/bin/env python3
"""`luce-pkg-admin remove`: released packages are pushed with stock Git, then removed through
the running owner's socket and offline. A removed package's repository, objects, release
files, index line and pages are gone, `luc` gets a clean "not found", a dependency is
refused unless forced, and every other package is untouched.

Usage: remove.py <registry> <admin> <account-fixture>. `luc`'s check runs when `LUC`
names a luc binary or one is on PATH."""
import functools
import http.server
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registry_client import Client, request, start, stop, free_port  # noqa: E402

registry, admin, fixture = [Path(value).resolve() for value in sys.argv[1:4]]
TOKEN = 'integration-store-token'


def git_id(root, content):
    return subprocess.run(['git', 'hash-object', '--stdin'], input=content, capture_output=True,
                          check=True, cwd=root).stdout.decode().strip()


def object_file(database, identity):
    return Path(str(database) + '.objects') / identity[:2] / identity[2:]


def remove(environment, target, coordinate, *flags, success=True):
    result = subprocess.run([str(admin), 'remove', str(target), coordinate, *flags], env=environment,
                            capture_output=True, text=True, timeout=300)
    assert (result.returncode == 0) == success, (result.returncode, result.stdout, result.stderr)
    return result.stdout


class Site(http.server.SimpleHTTPRequestHandler):
    """Caddy's part in production: the site directory as static files."""

    def log_message(self, *args):
        pass


with tempfile.TemporaryDirectory(prefix='registry-remove-', dir='/tmp') as temporary:
    root = Path(temporary)
    database = root / 'registry.db'
    socket_path = Path(str(database) + '.sock')
    site = root / 'site'
    subprocess.check_output([str(fixture), str(database)], text=True, timeout=30)
    port = free_port()
    environment = dict(os.environ, LUCE_REGISTRY_STORE_TOKEN=TOKEN, LUCE_REGISTRY_ORIGIN='https://pkg.luciaos.com',
                       LUCE_REGISTRY_SITE=str(site))
    site.mkdir()
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Site, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    site_port = server.server_address[1]

    def page(path):
        return request(site_port, 'GET', path)

    shared = b'# shared\nThe same bytes in two repositories are one object file.\n'
    own = b'only in the removed package\n'
    with (root / 'registry.log').open('w+') as log:
        process = start(registry, database, port, environment, log)
        try:
            status, session = request(port, 'POST', '/v1/sessions', {'name': 'testadmin', 'password': 'fixture-password'})
            assert status == 200
            client = Client(root, port, {'Authorization': 'Bearer ' + session.decode()})
            dependency = ('    def dependency "gone" {\n        str owner = "testadmin"\n'
                          '        str version = "^1.0.0"\n    }\n')
            packages = {
                'keep': ({'README.md': shared, 'keep.txt': b'kept\n'}, ''),
                'gone': ({'README.md': shared, 'gone.txt': own}, ''),
                'consumer': ({'README.md': b'# consumer\n'}, dependency),
            }
            for name, (files, extra) in packages.items():
                work, git_environment = client.repository(name, files, '1.0.0', extra)
                code, stderr, _ = client.push(work, git_environment, 'main', 'v1.0.0')
                assert code == 0, (name, stderr)
            for name in packages:
                assert page(f'/testadmin/{name}/')[0] == 200
                assert f'testadmin/{name}\t1.0.0\t' in (site / 'index').read_text()
            shared_id, own_id = git_id(root, shared), git_id(root, own)
            assert object_file(database, shared_id).is_file() and object_file(database, own_id).is_file()

            # A package another package's latest release depends on is refused, naming it.
            refused = remove(environment, socket_path, 'testadmin/gone', success=False)
            assert 'testadmin/consumer' in refused and '--force' in refused, refused
            assert page('/testadmin/gone/')[0] == 200 and object_file(database, own_id).is_file()
            remove(environment, socket_path, 'testadmin/nothing', success=False)
            print('PASS removal is refused for a dependency and an unknown package', flush=True)

            removed = remove(environment, socket_path, 'testadmin/gone', '--force')
            assert 'removed repository testadmin/gone: 1 release tags, 1 other refs' in removed, removed
            assert '1 shared with other repositories kept' in removed, removed
            assert 'its directory with 1 releases' in removed, removed
            # Repository, Git API, release files and pages are gone.
            assert request(port, 'GET', '/git/testadmin/gone/info/refs?service=git-upload-pack')[0] == 404
            for path in ('/testadmin/gone/', '/testadmin/gone/versions', '/testadmin/gone/1.0.0.pack',
                         '/testadmin/gone/1.0.0.prisma', '/testadmin/gone/1.0.0/tree/'):
                assert page(path)[0] == 404, path
            assert not (site / 'testadmin/gone').exists()
            index = (site / 'index').read_text()
            assert 'testadmin/gone\t' not in index and 'testadmin/keep\t' in index, index
            for view in ('', 'packages/'):
                front = page('/' + view)[1].decode()
                assert 'testadmin/gone' not in front and 'testadmin/keep' in front, view
            # Only the object no other repository lists loses its file.
            assert not object_file(database, own_id).exists()
            assert object_file(database, shared_id).is_file()
            luc = os.environ.get('LUC') or shutil.which('luc')
            if luc:
                result = subprocess.run([luc, 'latest', 'testadmin/gone'], capture_output=True, text=True, timeout=60,
                                        env=dict(os.environ, LUC_REGISTRY=f'http://127.0.0.1:{site_port}',
                                                 LUC_HOME=str(root / 'luc-home')))
                assert result.returncode != 0, result
                assert 'no such package' in result.stdout + result.stderr, result
                kept = subprocess.run([luc, 'latest', 'testadmin/keep'], capture_output=True, text=True, timeout=60,
                                      env=dict(os.environ, LUC_REGISTRY=f'http://127.0.0.1:{site_port}',
                                               LUC_HOME=str(root / 'luc-home')))
                assert kept.returncode == 0 and '1.0.0' in kept.stdout, kept
                print('PASS luc reports the removed package as not found', flush=True)
            else:
                print('SKIP luc check: no luc binary', flush=True)

            # The other packages are intact: clone, fsck, release files and page.
            client.clone('keep', root / 'keep-clone')
            assert (root / 'keep-clone/README.md').read_bytes() == shared
            assert page('/testadmin/keep/')[0] == 200 and page('/testadmin/keep/1.0.0.pack')[0] == 200
            assert request(port, 'GET', '/git/testadmin/keep/info/refs?service=git-upload-pack')[0] == 200
            # The name is free again.
            assert request(port, 'POST', '/v1/repositories', {'name': 'gone'}, client.session)[0] == 201
            print('PASS online removal: repository, objects, release files and pages gone; the rest intact', flush=True)
        finally:
            if sys.exc_info()[0] is not None:
                log.flush()
                log.seek(0)
                print('REGISTRY LOG:\n' + log.read(), file=sys.stderr, flush=True)
            stop(process)
        # Offline, against the database path, with the registry stopped.
        removed = remove(environment, database, 'testadmin/consumer')
        assert 'removed repository testadmin/consumer: 1 release tags' in removed, removed
        assert not (site / 'testadmin/consumer').exists()
        process = start(registry, database, port, environment, log)
        try:
            assert request(port, 'GET', '/git/testadmin/consumer/info/refs?service=git-upload-pack')[0] == 404
            client.clone('keep', root / 'keep-after-restart')
            index = (site / 'index').read_text()
            assert index.startswith('testadmin/keep\t') and index.count('\n') == 1, index
        finally:
            stop(process)
    server.shutdown()
print('PASS offline removal; the remaining package survives a restart', flush=True)
