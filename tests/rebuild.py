#!/usr/bin/env python3
"""`luce-pkg-admin rebuild-site` and `withdraw`: the public site is derived from the database
alone, so a rebuild into a new directory matches, byte for byte, the site the pushes wrote.
Withdrawn releases lose their tag and leave the next rebuild; the newest release stays.

Usage: rebuild.py <registry> <admin> <account-fixture>"""
import filecmp
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registry_client import Client, request, start, stop, free_port  # noqa: E402

registry, admin, fixture = [Path(value).resolve() for value in sys.argv[1:4]]
TOKEN = 'integration-store-token'


def run_admin(environment, *arguments, success=True):
    result = subprocess.run([str(admin), *[str(a) for a in arguments]], env=environment,
                            capture_output=True, text=True, timeout=300)
    assert (result.returncode == 0) == success, (arguments, result.returncode, result.stdout, result.stderr)
    return result.stdout + result.stderr


def files_below(root):
    return sorted(str(path.relative_to(root)) for path in root.rglob('*') if path.is_file())


def same_tree(left, right):
    assert files_below(left) == files_below(right), (set(files_below(left)) ^ set(files_below(right)))
    for relative in files_below(left):
        assert filecmp.cmp(left / relative, right / relative, shallow=False), relative


def release(work, environment, version, extra=''):
    """Commit a new package.prisma version in `work` and tag it."""
    text = (work / 'package.prisma').read_text()
    start_of = text.index('str version = "') + len('str version = "')
    text = text[:start_of] + version + text[text.index('"', start_of):]
    (work / 'package.prisma').write_text(text)
    (work / 'CHANGES').write_text(f'{version}\n')
    for args in (('add', '.'), ('commit', '-qm', version), ('tag', '-a', f'v{version}', '-m', f'release {version}')):
        subprocess.run(['git', '-C', str(work), *args], env=environment, check=True, capture_output=True, timeout=60)


with tempfile.TemporaryDirectory(prefix='registry-rebuild-', dir='/tmp') as temporary:
    root = Path(temporary)
    database = root / 'registry.db'
    socket_path = Path(str(database) + '.sock')
    site = root / 'site'
    site.mkdir()
    subprocess.check_output([str(fixture), str(database)], text=True, timeout=30)
    port = free_port()
    environment = dict(os.environ, LUCE_REGISTRY_STORE_TOKEN=TOKEN, LUCE_REGISTRY_ORIGIN='https://pkg.luciaos.com',
                       LUCE_REGISTRY_SITE=str(site))
    with (root / 'registry.log').open('w+') as log:
        process = start(registry, database, port, environment, log)
        try:
            status, session = request(port, 'POST', '/v1/sessions', {'name': 'testadmin', 'password': 'fixture-password'})
            assert status == 200
            client = Client(root, port, {'Authorization': 'Bearer ' + session.decode()})
            # A library with three releases, an image its README shows, and an application.
            pixel = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                                  '1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082')
            library, library_environment = client.repository(
                'lib', {'README.md': b'# lib\n![dot](dot.png)\n', 'dot.png': pixel, 'lib.lucb': b'pub let x = 1\n'}, '1.0.0')
            release(library, library_environment, '1.1.0')
            release(library, library_environment, '1.2.0')
            code, stderr, _ = client.push(library, library_environment, 'main', 'v1.0.0', 'v1.1.0', 'v1.2.0')
            assert code == 0, stderr
            dependency = ('    def dependency "lib" {\n        str owner = "testadmin"\n'
                          '        str version = "^1.2.0"\n    }\n')
            application, application_environment = client.repository('app', {'README.md': b'# app\n'}, '0.1.0', dependency)
            code, stderr, _ = client.push(application, application_environment, 'main', 'v0.1.0')
            assert code == 0, stderr
            assert (site / 'testadmin/lib/versions').read_text().count('\n') == 3
            assert (site / 'testadmin/lib/1.2.0/raw/dot.png').read_bytes() == pixel

            # Online, through the socket: the rebuild equals what the pushes wrote.
            rebuilt = root / 'rebuilt'
            output = run_admin(environment, 'rebuild-site', socket_path, rebuilt)
            assert 'rebuilt' in output and '2 packages, 4 releases, 0 failed' in output, output
            same_tree(site, rebuilt)
            assert 'already holds a site' in run_admin(environment, 'rebuild-site', socket_path, rebuilt, success=False)
            print('PASS a rebuild from the database equals the site the pushes wrote', flush=True)

            # Withdraw the two older library releases; the newest and unknown ones are refused.
            refused = run_admin(environment, 'withdraw', socket_path, 'testadmin/lib', '1.2.0', success=False)
            assert 'newest release' in refused, refused
            assert 'no such release' in run_admin(environment, 'withdraw', socket_path, 'testadmin/lib', '9.9.9', success=False)
            assert 'no such repository' in run_admin(environment, 'withdraw', socket_path, 'testadmin/none', '1.0.0', success=False)
            output = run_admin(environment, 'withdraw', socket_path, 'testadmin/lib', '1.0.0', '1.1.0')
            assert 'withdrew testadmin/lib 1.0.0' in output and 'withdrew testadmin/lib 1.1.0' in output, output
            advertised = request(port, 'GET', '/git/testadmin/lib/info/refs?service=git-upload-pack')[1].decode('latin-1')
            assert 'refs/tags/v1.2.0' in advertised and 'refs/tags/v1.0.0' not in advertised and 'refs/tags/v1.1.0' not in advertised
            client.clone('lib', root / 'lib-clone')
            pruned = root / 'pruned'
            pruned.mkdir()  # prepared empty, as an operator does for the site's owner and mode
            output = run_admin(environment, 'rebuild-site', socket_path, pruned)
            assert '2 packages, 2 releases, 0 failed' in output, output
            versions = (pruned / 'testadmin/lib/versions').read_text()
            assert versions.startswith('1.2.0 ') and versions.count('\n') == 1, versions
            assert versions == (site / 'testadmin/lib/versions').read_text().splitlines(keepends=True)[2]
            for gone in ('1.0.0.pack', '1.0.0.prisma', '1.0.0.notes', '1.0.0', '1.1.0.pack', '1.1.0'):
                assert not (pruned / 'testadmin/lib' / gone).exists(), gone
            for kept in ('testadmin/lib/1.2.0.pack', 'testadmin/lib/1.2.0.prisma', 'testadmin/lib/1.2.0.notes',
                         'testadmin/lib/1.2.0/raw/dot.png', 'testadmin/app/0.1.0.pack', 'index'):
                assert filecmp.cmp(site / kept, pruned / kept, shallow=False), kept
            # The package page lists only the releases that remain.
            page = (pruned / 'testadmin/lib/index.html').read_text()
            assert '1.2.0' in page and '1.1.0' not in page and '1.0.0' not in page
            print('PASS withdrawn releases leave the database and the next rebuild; the newest stays', flush=True)
        finally:
            if sys.exc_info()[0] is not None:
                log.flush()
                log.seek(0)
                print('REGISTRY LOG:\n' + log.read(), file=sys.stderr, flush=True)
            stop(process)
        # Offline, against the database path, with the registry stopped.
        offline = root / 'offline'
        assert '2 packages, 2 releases, 0 failed' in run_admin(environment, 'rebuild-site', database, offline)
        same_tree(pruned, offline)
print('PASS an offline rebuild equals the online one', flush=True)
