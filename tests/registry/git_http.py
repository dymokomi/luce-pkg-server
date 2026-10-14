"""Real stock Git client against native HTTP receive-pack; no runtime Git dependency. The
registry takes the creation of release tags and nothing else, and serves no Git reads."""
import base64
import gzip
import hashlib
import os
import struct
import subprocess
import zlib
import http.client

from registry_client import released


def transfer(port, method, path, body=b'', headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=90)
    try:
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def manifest(version):
    return ('#prisma 4.0\ndef package "git-wire" {\n    str owner = "testuser"\n'
            f'    str version = "{version}"\n    str kind = "package"\n    str language = "luce-base"\n'
            '    str description = "Release fixture"\n    str license = "MIT OR Apache-2.0"\n    str readme = "README.md"\n}\n')


def check(port, session_headers, token, root, request, create_repository=None):
    """Returns the tag object release 1.3.0's ref names."""
    if create_repository is None:
        assert request(port, 'POST', '/v1/repositories', {'name': 'git-wire'}, session_headers)[0] == 201
    else:
        create_repository('git-wire')
    endpoint = f'http://127.0.0.1:{port}/git/testuser/git-wire'
    headers = {'Authorization': 'Basic ' + base64.b64encode(b'testuser:' + token).decode()}
    receive = {**headers, 'Content-Type': 'application/x-git-receive-pack-request'}
    discovery = '/git/testuser/git-wire/info/refs?service=git-receive-pack'
    assert request(port, 'GET', discovery)[0] == 401
    assert request(port, 'GET', discovery, headers=session_headers)[0] == 401
    assert request(port, 'GET', '/git/testadmin/git-wire/info/refs?service=git-receive-pack', headers=headers)[0] == 401
    assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=bad', headers=headers)[0] == 403
    assert request(port, 'HEAD', discovery, headers=headers) == (200, b'')
    # No Git reads: no upload-pack discovery, with or without a credential, and no route.
    for credentials in ({}, headers):
        assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-upload-pack', headers=credentials)[0] == 403
    assert request(port, 'POST', '/git/testuser/git-wire/git-upload-pack',
                   headers={**headers, 'Content-Type': 'application/x-git-upload-pack-request'})[0] in (404, 405)
    repo = root / 'git-client'
    askpass = root / 'git-askpass.sh'
    askpass.write_text('#!/bin/sh\ncase "$1" in\n  *Username*) printf "%s\\n" "$LUCE_GIT_USERNAME" ;;\n  *Password*) printf "%s\\n" "$LUCE_GIT_TOKEN" ;;\n  *) exit 1 ;;\nesac\n')
    askpass.chmod(0o700)
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.test',
               GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.test',
               GIT_ASKPASS=str(askpass), LUCE_GIT_USERNAME='testuser', LUCE_GIT_TOKEN=token.decode())

    def git(*args, success=True, input=None):
        result = subprocess.run(['git', '-C', str(repo), *args], env=env,
                                input=input, capture_output=True, timeout=300)
        if success: assert result.returncode == 0, (args, result.stderr)
        else: assert result.returncode != 0, args
        return result.stdout if success else result.stderr

    def advertised():
        status, advertisement = request(port, 'GET', discovery, headers=headers)
        assert status == 200, status
        return advertisement

    repo.mkdir()
    git('init', '--object-format=sha1', '-b', 'main', '-q')
    assert b'403' in git('clone', endpoint, str(root / 'git-clone'), success=False)
    (repo / 'main.lucb').write_text('pub func main() -> i32:\n    return 0\n')
    # Large near-identical revisions force stock Git to use a remote delta base.
    source = b''.join(hashlib.sha256(str(i).encode()).hexdigest().encode() + b'\n' for i in range(4096))
    (repo / 'large.txt').write_bytes(source)
    git('add', 'main.lucb', 'large.txt')
    git('commit', '-qm', 'initial native registry fixture')
    git('remote', 'add', 'origin', endpoint)
    assert token not in (repo / '.git/config').read_bytes()
    (repo / 'package.prisma').write_text(manifest('1.3.0'))
    (repo / 'docs').mkdir()
    (repo / 'docs/shot.png').write_bytes(b'\x89PNG fixture')
    (repo / 'README.md').write_text('# git-wire\n\n![shot](docs/shot.png) and [notes](docs/notes.md) and [bad](javascript:alert(1))\n')
    git('add', 'package.prisma', 'docs', 'README.md')
    git('commit', '-qm', 'declare package 1.3.0')
    first = git('rev-parse', 'HEAD').strip()
    released_commit = first.decode()

    # A version tag publishes a static, history-free release.
    site = root / 'site' / 'testuser' / 'git-wire'
    git('tag', '-a', 'v9.9.9', '-m', 'wrong version')
    assert b'version must match the release tag' in git('push', 'origin', 'v9.9.9', success=False)
    assert not site.exists()
    # Release notes are mandatory: a lightweight tag is refused.
    git('tag', 'v1.3.0')
    assert b'release notes are required' in git('push', 'origin', 'v1.3.0', success=False)
    git('tag', '-d', 'v1.3.0')
    assert not site.exists()
    git('tag', '-a', 'v1.3.0', '-m', 'First fixture release.\n\n- adds <package.prisma>\n')
    tag = git('rev-parse', 'v1.3.0').strip()
    git('push', '--porcelain', 'origin', 'v1.3.0')
    assert (site / '1.3.0.notes').read_text() == 'First fixture release.\n\n- adds <package.prisma>'
    pack = (site / '1.3.0.pack').read_bytes()
    assert (site / '1.3.0.prisma').read_bytes() == (repo / 'package.prisma').read_bytes()
    assert (site / 'versions').read_text() == f'1.3.0 {hashlib.sha256(pack).hexdigest()} {released_commit}\n'
    assert (root / 'site' / 'index').read_text() == 'testuser/git-wire\t1.3.0\tRelease fixture\tpackage\n'
    front = (root / 'site' / 'index.html').read_text()
    assert '<a class="card" href="/testuser/git-wire/">' in front and 'Release fixture' in front
    assert 'Find and install Luce packages' in front and '0 applications &middot; 0 tools &middot; 1 package</p>' in front and '<a href="/tools/">Tools</a>' in front and '<section class="kind" id="packages">' in front and '<a href="/applications/">Applications</a>' in front
    assert '<a class="here" href="/packages/">Packages</a>' in (root / 'site' / 'packages' / 'index.html').read_text()
    assert 'id="applications"' not in front
    detail = (site / 'index.html').read_text()
    assert '<h1>testuser/git-wire</h1>' in detail and 'luc add testuser/git-wire' in detail
    assert 'License <code>MIT OR Apache-2.0</code>.' in detail
    assert hashlib.sha256(pack).hexdigest() in detail and released_commit[:12] in detail
    assert 'First fixture release.' in detail and '- adds &lt;package.prisma&gt;' in detail
    assert '<img src="/testuser/git-wire/1.3.0/raw/docs/shot.png"' in detail and 'href="/testuser/git-wire/1.3.0/blob/docs/notes.md.html"' in detail and 'href="#">bad' in detail
    assert (site / '1.3.0/raw/docs/shot.png').read_bytes() == b'\x89PNG fixture'
    listing = (site / '1.3.0/tree/index.html').read_text()
    assert '/testuser/git-wire/1.3.0/blob/package.prisma.html' in listing and 'large.txt' in listing
    page = (site / '1.3.0/blob/main.lucb.html').read_text()
    assert '<span class="l" id="L1"><span class="k">pub</span> <span class="k">func</span> <span class="d">main</span>() -&gt; <span class="t">i32</span>:</span>' in page and 'id="L2"' in page
    unpacked = root / 'release-unpacked'
    subprocess.run(['git', 'init', '-q', str(unpacked)], env=env, check=True, timeout=30)
    subprocess.run(['git', '-C', str(unpacked), 'unpack-objects'], input=pack, env=env, check=True, capture_output=True, timeout=30)
    listed = subprocess.check_output(['git', '-C', str(unpacked), 'ls-tree', '-r', '--name-only', released_commit], env=env, timeout=30)
    assert b'package.prisma' in listed.split() and b'large.txt' in listed.split()
    parents = subprocess.check_output(['git', '-C', str(unpacked), 'cat-file', '-p', released_commit], env=env, timeout=30)
    missing = subprocess.run(['git', '-C', str(unpacked), 'cat-file', '-e', parents.split(b'parent ')[1][:40].decode()], env=env, capture_output=True, timeout=30)
    assert missing.returncode != 0, 'a release pack carries no history'
    print('PASS a version tag publishes an immutable static release; mismatched and note-less tags are refused', flush=True)

    # Only the creation of a release tag is taken. A branch and an ordinary tag are refused
    # with the reason; so is moving a release, and stock Git will not even ask to delete
    # one, since deletion is not offered. The raw deletion is refused with the reason.
    for refused in (('push', 'origin', 'main'), ('push', 'origin', 'HEAD:refs/heads/topic')):
        assert b'only release tags' in git(*refused, success=False)
    git('tag', '-a', 'annotated', '-m', 'an ordinary tag')
    assert b'only release tags' in git('push', 'origin', 'refs/tags/annotated', success=False)
    assert b'cannot be moved or deleted' in git('push', '--force', 'origin', 'HEAD~1:refs/tags/v1.3.0', success=False)
    git('push', 'origin', ':refs/tags/v1.3.0', success=False)
    command = tag + b' ' + b'0' * 40 + b' refs/tags/v1.3.0\0 report-status'
    status, report = transfer(port, 'POST', '/git/testuser/git-wire/git-receive-pack',
                              f'{len(command) + 4:04x}'.encode() + command + b'0000', receive)
    assert status == 200 and b'ng refs/tags/v1.3.0 release: a release tag cannot be moved or deleted\n' in report, report
    advertisement = advertised()
    assert tag + b' refs/tags/v1.3.0\0' in advertisement and b'delete-refs' not in advertisement, advertisement
    assert b'refs/heads/' not in advertisement and b'refs/tags/annotated' not in advertisement, advertisement
    git('push', '--porcelain', 'origin', 'v1.3.0')  # Up-to-date discovery succeeds.
    print('PASS branches, ordinary tags, moves and deletions are refused, with the reason', flush=True)

    # The next release as a thin pack: its changed blob is a delta against the stored one.
    (repo / 'large.txt').write_bytes(source[:100000] + b'changed line\n' + source[100000:])
    (repo / 'package.prisma').write_text(manifest('1.3.1'))
    git('add', 'large.txt', 'package.prisma')
    git('commit', '-qm', 'incremental release')
    git('tag', '-a', 'v1.3.1', '-m', 'Second fixture release.')
    second = git('rev-parse', 'v1.3.1').strip()
    thin = git('pack-objects', '--stdout', '--thin', '--revs', input=second + b'\n^' + first + b'\n')
    # Assert the oracle actually emitted a REF delta against the old remote blob.
    old_blob = bytes.fromhex(git('rev-parse', first.decode() + ':large.txt').decode().strip())
    at, bases = 12, []
    for _ in range(struct.unpack('>I', thin[8:12])[0]):
        header = thin[at]
        form = (header >> 4) & 7
        at += 1
        while header & 128:
            header = thin[at]
            at += 1
        if form == 7:
            bases.append(thin[at:at + 20])
            at += 20
        else:
            assert form in (1, 2, 3, 4), form
        decoder = zlib.decompressobj()
        decoder.decompress(thin[at:-20])
        assert decoder.eof
        at = len(thin) - 20 - len(decoder.unused_data)
    assert at == len(thin) - 20 and old_blob in bases
    command = b'0' * 40 + b' ' + second + b' refs/tags/v1.3.1\0 report-status atomic'
    status, report = transfer(port, 'POST', '/git/testuser/git-wire/git-receive-pack',
                              f'{len(command) + 4:04x}'.encode() + command + b'0000' + thin, receive)
    assert status == 200 and b'ok refs/tags/v1.3.1\n' in report, report
    assert released(root / 'site', 'testuser/git-wire', '1.3.1', 'large.txt') == (repo / 'large.txt').read_bytes()
    # A release whose graph is not whole publishes nothing.
    packet = b'0' * 40 + b' ' + b'f' * 40 + b' refs/tags/v7.0.0\0 report-status atomic'
    pack_head = b'PACK\0\0\0\2\0\0\0\0'
    broken_graph = f'{len(packet) + 4:04x}'.encode() + packet + b'0000' + pack_head + hashlib.sha1(pack_head).digest()
    status, report = transfer(port, 'POST', '/git/testuser/git-wire/git-receive-pack', broken_graph, receive)
    assert status == 200 and b'ng refs/tags/v7.0.0 transaction rejected\n' in report, report
    advertisement = advertised()
    assert b'refs/tags/v7.0.0' not in advertisement and second + b' refs/tags/v1.3.1\n' in advertisement, advertisement
    assert not (site / '7.0.0.pack').exists()
    # Wrong Content-Type, malformed framing and an encoded body must not mutate refs: Git
    # sends a push as it is.
    assert request(port, 'POST', '/git/testuser/git-wire/git-receive-pack', headers=headers)[0] == 415
    assert request(port, 'POST', '/git/testuser/git-wire/git-receive-pack', headers=receive)[0] == 400
    assert transfer(port, 'POST', '/git/testuser/git-wire/git-receive-pack', gzip.compress(broken_graph),
                    {**receive, 'Content-Encoding': 'gzip'})[0] == 415
    # Without a credential nothing is pushed.
    anonymous_env = {key: value for key, value in env.items() if key not in ('GIT_ASKPASS', 'LUCE_GIT_TOKEN', 'LUCE_GIT_USERNAME')}
    git('tag', '-a', 'v1.4.0', '-m', 'anonymous')
    refused = subprocess.run(['git', '-C', str(repo), 'push', 'origin', 'v1.4.0'], env=anonymous_env, capture_output=True, timeout=90)
    assert refused.returncode != 0 and b'refs/tags/v1.4.0' not in advertised()
    print('PASS a thin-pack release, an incomplete graph refused whole, body checks and no anonymous push', flush=True)

    # A release too large for one push is refused with the limit it exceeded, by name or as
    # the request's size.
    for version, make in (('2.0.0', lambda i: os.urandom(24 << 20)), ('2.1.0', lambda i: bytes([i]) * (30 << 20))):
        git('checkout', '-q', '--orphan', f'large-{version}')
        git('rm', '-q', '-rf', '--cached', '.')
        for i in range(3):
            (repo / f'part{i}.bin').write_bytes(make(i))
        (repo / 'package.prisma').write_text(manifest(version))
        git('add', 'package.prisma', *[f'part{i}.bin' for i in range(3)])
        git('commit', '-q', '-m', f'large {version}')
        git('tag', '-a', f'v{version}', '-m', f'large {version}')
        stderr = git('push', 'origin', f'v{version}', success=False)
        assert any(sign in stderr for sign in (b'limit exceeded', b'HTTP 413', b'RPC failed')), stderr[-400:]
        for i in range(3):
            (repo / f'part{i}.bin').unlink()
        git('checkout', '-q', '-f', 'main')
    assert not (site / '2.0.0.pack').exists() and not (site / '2.1.0.pack').exists()
    print('PASS a release over the push limits is refused, naming the limit', flush=True)
    return tag
