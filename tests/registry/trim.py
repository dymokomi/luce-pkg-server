#!/usr/bin/env python3
"""`luce-pkg-admin trim`: the registry keeps releases and GitHub keeps history. A store from
before release-only pushes holds a branch with its history; the legacy fixture writes one
(migrated to object files, as production's was), then its releases are pushed. Trim reduces
it to its release tags and what they reach through tag, commit and tree. Objects only
history or the branch reached lose their listing, and their file unless another repository
lists them; release files and listings are byte for byte what they were; a release pushed
afterwards on top of the trimmed store still publishes.

Usage: trim.py <registry> <admin> <legacy-fixture>."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registry_client import Client, request, start, stop, free_port  # noqa: E402

registry, admin, legacy = [Path(value).resolve() for value in sys.argv[1:4]]
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
    site = root / 'site'
    site.mkdir()
    environment = dict(os.environ, LUCE_REGISTRY_STORE_TOKEN=TOKEN, LUCE_REGISTRY_ORIGIN='https://pkg.luciaos.com',
                       LUCE_REGISTRY_SITE=str(site))
    git_environment = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0',
                           GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.test',
                           GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.test')
    shared = b'# shared\nThe same bytes in two repositories are one object file.\n'
    early = b'only in the first commit, before any release\n'
    unreleased = b'only on main after the last release\n'
    work = root / 'legacy'
    work.mkdir()

    def git(*args, input=None):
        return subprocess.run(['git', '-C', str(work), *args], env=git_environment, input=input, check=True,
                              capture_output=True, timeout=600).stdout

    def release(version, notes):
        (work / 'package.prisma').write_text(
            f'#prisma 4.0\ndef package "legacy" {{\n    str owner = "testadmin"\n    str version = "{version}"\n'
            '    str kind = "package"\n    str language = "luce-base"\n    str description = "Trim fixture"\n}\n')
        git('add', '.')
        git('commit', '-qm', f'legacy {version}')
        git('tag', '-a', f'v{version}', '-m', notes)

    # A first commit no release reaches, two releases, then unreleased work: main's history.
    git('init', '-q', '-b', 'main', '--object-format=sha1')
    (work / 'README.md').write_bytes(shared)
    (work / 'early.txt').write_bytes(early)
    git('add', '.')
    git('commit', '-qm', 'early')
    (work / 'early.txt').unlink()
    release('1.0.0', 'first')
    release('1.0.1', 'second')
    (work / 'later.txt').write_bytes(unreleased)
    git('add', '.')
    git('commit', '-qm', 'unreleased work')
    pack = root / 'main.pack'
    pack.write_bytes(git('pack-objects', '--revs', '--stdout', input=b'main\n'))
    old = root / 'old' / 'registry.db'
    old.parent.mkdir()
    subprocess.run([str(legacy), str(old), str(pack), git('rev-parse', 'main').strip().decode()], env=environment,
                   check=True, capture_output=True, timeout=120)
    database = root / 'registry.db'
    subprocess.run([str(admin), 'migrate', str(old), str(database)], env=environment, check=True, capture_output=True, timeout=300)
    port = free_port()
    with (root / 'registry.log').open('w+') as log:
        process = start(registry, database, port, environment, log)
        try:
            status, session = request(port, 'POST', '/v1/sessions', {'name': 'testadmin', 'password': 'fixture-password'})
            assert status == 200
            client = Client(root, port, {'Authorization': 'Bearer ' + session.decode()})
            keep, keep_environment = client.repository('keep', {'README.md': shared}, '1.0.0')
            assert client.push(keep, keep_environment, 'v1.0.0')[0] == 0
            # The releases go up as release tags: the branch stays only in the old store.
            git('remote', 'add', 'origin', client.endpoint('legacy'))
            legacy_environment = client.environment('legacy')
            code, stderr, _ = client.push(work, legacy_environment, 'v1.0.0', 'v1.0.1')
            assert code == 0, stderr
            early_id, unreleased_id, shared_id = git_id(root, early), git_id(root, unreleased), git_id(root, shared)
            for identity in (early_id, unreleased_id, shared_id):
                assert object_file(database, identity).is_file()
            before = published(site)
            assert 'testadmin/legacy/1.0.1.pack' in before and 'testadmin/legacy/versions' in before, before
        finally:
            stop(process)

        # Offline: refused through the socket, then run against the database path.
        refused = subprocess.run([str(admin), 'trim', str(database) + '.sock', 'testadmin/legacy'], env=environment,
                                 capture_output=True, text=True, timeout=300)
        assert refused.returncode != 0
        result = subprocess.run([str(admin), 'trim', str(database), '--all'], env=environment,
                                capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert 'testadmin/legacy: kept 2 release tags' in result.stdout, result.stdout
        assert 'removed 1 other refs' in result.stdout, result.stdout
        assert 'testadmin/keep: kept 1 release tags' in result.stdout, result.stdout
        # History and the branch's work are gone; what a release reaches, or another
        # repository lists, stays; the site is untouched.
        assert not object_file(database, early_id).exists()
        assert not object_file(database, unreleased_id).exists()
        assert object_file(database, shared_id).is_file()
        assert published(site) == before
        print('PASS trim keeps the releases and what they reach; history and the branch go', flush=True)

        process = start(registry, database, port, environment, log)
        try:
            status, advertisement = client.discovery('legacy')
            assert status == 200 and b'refs/tags/v1.0.1' in advertisement, advertisement
            assert b'refs/heads/' not in advertisement, advertisement
            # A release on top of the trimmed store: its parent is there, the history behind not.
            legacy_environment = client.environment('legacy')
            git('reset', '-q', '--hard', 'v1.0.1')
            release('1.0.2', 'third')
            code, stderr, _ = client.push(work, legacy_environment, 'v1.0.2')
            assert code == 0, stderr
            assert (site / 'testadmin/legacy/1.0.2.pack').is_file()
            assert published(site).items() >= before.items() - {('testadmin/legacy/versions', before['testadmin/legacy/versions'])}
        finally:
            if sys.exc_info()[0] is not None:
                log.flush()
                log.seek(0)
                print('REGISTRY LOG:\n' + log.read(), file=sys.stderr, flush=True)
            stop(process)
print('PASS a release pushed on top of a trimmed store publishes', flush=True)
