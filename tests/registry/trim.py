#!/usr/bin/env python3
"""`luce-pkg-admin trim`: the registry keeps releases and GitHub keeps history, so a package
pushed the old way (a branch with history, an ordinary tag, two releases) is reduced to its
release tags and what they reach through tag, commit and tree. Objects only history or a
branch reached lose their listing, and their file unless another repository lists them;
release files and listings are byte for byte what they were; a release pushed afterwards on
top of trimmed history still publishes.

Usage: trim.py <registry> <admin> <account-fixture>."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registry_client import Client, request, start, stop, free_port  # noqa: E402

registry, admin, fixture = [Path(value).resolve() for value in sys.argv[1:4]]
TOKEN = 'integration-store-token'


def git_id(root, content):
    return subprocess.run(['git', 'hash-object', '--stdin'], input=content, capture_output=True,
                          check=True, cwd=root).stdout.decode().strip()


def object_file(database, identity):
    return Path(str(database) + '.objects') / identity[:2] / identity[2:]


def published(site):
    """Every release file and listing on the site, with its digest."""
    return {path.relative_to(site).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(site.rglob('*')) if path.is_file()
            and (path.name == 'versions' or path.suffix in ('.pack', '.prisma', '.notes'))}


with tempfile.TemporaryDirectory(prefix='registry-trim-', dir='/tmp') as temporary:
    root = Path(temporary)
    database = root / 'registry.db'
    site = root / 'site'
    site.mkdir()
    subprocess.check_output([str(fixture), str(database)], text=True, timeout=30)
    port = free_port()
    environment = dict(os.environ, LUCE_REGISTRY_STORE_TOKEN=TOKEN, LUCE_REGISTRY_ORIGIN='https://pkg.luciaos.com',
                       LUCE_REGISTRY_SITE=str(site))
    shared = b'# shared\nThe same bytes in two repositories are one object file.\n'
    early = b'only in the first commit, before any release\n'
    unreleased = b'only on main after the last release\n'
    with (root / 'registry.log').open('w+') as log:
        process = start(registry, database, port, environment, log)
        try:
            status, session = request(port, 'POST', '/v1/sessions', {'name': 'testadmin', 'password': 'fixture-password'})
            assert status == 200
            client = Client(root, port, {'Authorization': 'Bearer ' + session.decode()})
            keep, keep_environment = client.repository('keep', {'README.md': shared}, '1.0.0')
            assert client.push(keep, keep_environment, 'main', 'v1.0.0')[0] == 0
            # film: a first commit no release reaches, two releases, then unreleased work and a tag.
            film, film_environment = client.repository('film', {'README.md': shared, 'early.txt': early})

            def git(*args):
                return subprocess.run(['git', '-C', str(film), *args], env=film_environment, check=True,
                                      capture_output=True, timeout=600).stdout.decode()

            def release(version, notes):
                (film / 'package.prisma').write_text(
                    f'#prisma 4.0\ndef package "film" {{\n    str owner = "testadmin"\n    str version = "{version}"\n'
                    '    str kind = "package"\n    str language = "luce-base"\n    str description = "Trim fixture"\n}\n')
                git('add', '.')
                git('commit', '-qm', f'film {version}')
                git('tag', '-a', f'v{version}', '-m', notes)

            (film / 'early.txt').unlink()
            release('1.0.0', 'first')
            release('1.0.1', 'second')
            (film / 'later.txt').write_bytes(unreleased)
            git('add', '.')
            git('commit', '-qm', 'unreleased work')
            git('tag', 'ordinary')
            assert client.push(film, film_environment, 'main', 'v1.0.0', 'v1.0.1', 'ordinary')[0] == 0
            early_id, unreleased_id, shared_id = git_id(root, early), git_id(root, unreleased), git_id(root, shared)
            for identity in (early_id, unreleased_id, shared_id):
                assert object_file(database, identity).is_file()
            before = published(site)
            assert 'testadmin/film/1.0.1.pack' in before and 'testadmin/film/versions' in before, before
        finally:
            stop(process)

        # Offline: refused through the socket, then run against the database path.
        refused = subprocess.run([str(admin), 'trim', str(database) + '.sock', 'testadmin/film'], env=environment,
                                 capture_output=True, text=True, timeout=300)
        assert refused.returncode != 0
        result = subprocess.run([str(admin), 'trim', str(database), '--all'], env=environment,
                                capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert 'testadmin/film: kept 2 release tags' in result.stdout, result.stdout
        assert 'removed 2 other refs' in result.stdout, result.stdout
        assert 'testadmin/keep: kept 1 release tags' in result.stdout, result.stdout
        # History and the branch's work are gone; what a release reaches, or another
        # repository lists, stays; the site is untouched.
        assert not object_file(database, early_id).exists()
        assert not object_file(database, unreleased_id).exists()
        assert object_file(database, shared_id).is_file()
        assert published(site) == before
        print('PASS trim keeps the releases and what they reach; history, branches and tags go', flush=True)

        process = start(registry, database, port, environment, log)
        try:
            status, advertisement = request(port, 'GET', '/git/testadmin/film/info/refs?service=git-upload-pack')
            assert status == 200 and b'refs/tags/v1.0.1' in advertisement, advertisement
            assert b'refs/heads/' not in advertisement and b'refs/tags/ordinary' not in advertisement, advertisement
            # A release on top of the trimmed history: its parent is there, the history behind not.
            film_environment = client.environment('film')
            git('reset', '-q', '--hard', 'v1.0.1')
            release('1.0.2', 'third')
            code, stderr, _ = client.push(film, film_environment, 'v1.0.2')
            assert code == 0, stderr
            assert (site / 'testadmin/film/1.0.2.pack').is_file()
            assert published(site).items() >= before.items() - {('testadmin/film/versions', before['testadmin/film/versions'])}
        finally:
            if sys.exc_info()[0] is not None:
                log.flush()
                log.seek(0)
                print('REGISTRY LOG:\n' + log.read(), file=sys.stderr, flush=True)
            stop(process)
print('PASS a release pushed on top of trimmed history publishes', flush=True)
