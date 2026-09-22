"""Real stock Git client against native HTTP receive-pack; no runtime Git dependency."""
import base64
import os
from pathlib import Path
import subprocess
import hashlib
import struct
import zlib
from object_http import transfer


def check(port, session_headers, token, read_token, root, request, create_repository=None):
    if create_repository is None:
        assert request(port, 'POST', '/v1/repositories', {'name': 'git-wire'}, session_headers)[0] == 201
    else:
        create_repository('git-wire')
    endpoint = f'http://127.0.0.1:{port}/git/testuser/git-wire'
    headers = {'Authorization': 'Basic ' + base64.b64encode(b'testuser:' + token).decode()}
    read_headers = {'Authorization': 'Basic ' + base64.b64encode(b'testuser:' + read_token).decode()}
    assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-receive-pack')[0] == 401
    assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-receive-pack', headers=session_headers)[0] == 401
    assert request(port, 'GET', '/git/testadmin/git-wire/info/refs?service=git-receive-pack', headers=headers)[0] == 401
    assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=bad', headers=headers)[0] == 403
    assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-receive-pack', headers=read_headers)[0] == 401
    assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-upload-pack', headers=read_headers)[0] == 200
    assert request(port, 'HEAD', '/git/testuser/git-wire/info/refs?service=git-receive-pack', headers=headers) == (200, b'')
    repo = root / 'git-client'
    askpass = root / 'git-askpass.sh'
    askpass.write_text('#!/bin/sh\ncase "$1" in\n  *Username*) printf "%s\\n" "$LUCE_GIT_USERNAME" ;;\n  *Password*) printf "%s\\n" "$LUCE_GIT_TOKEN" ;;\n  *) exit 1 ;;\nesac\n')
    askpass.chmod(0o700)
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.test',
               GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.test',
               GIT_ASKPASS=str(askpass), LUCE_GIT_USERNAME='testuser', LUCE_GIT_TOKEN=token.decode(),
               GIT_TRACE_PACKET='1')

    def git(*args, success=True, input=None):
        result = subprocess.run(['git', '-C', str(repo), *args], env=env,
                                input=input, capture_output=True, timeout=90)
        if success: assert result.returncode == 0, (args, result.stderr)
        else: assert result.returncode != 0, args
        return result.stdout

    repo.mkdir()
    git('init', '--object-format=sha1', '-b', 'main', '-q')
    git('clone', endpoint, str(root / 'git-empty-clone'))
    (repo / 'main.lucb').write_text('pub func main() -> i32:\n    return 0\n')
    (repo / 'luce.toml').write_text('''[package]
name = "git_wire"
version = "1.2.6"
language = "luce-base"

[registry.dependencies]
"testadmin/core" = "^1.0.0"
"testadmin/render-kit" = "2.1.0"
''')
    # Large near-identical revisions force stock Git to use a remote delta base.
    source = b''.join(hashlib.sha256(str(i).encode()).hexdigest().encode() + b'\n' for i in range(4096))
    (repo / 'large.txt').write_bytes(source)
    git('add', 'main.lucb', 'luce.toml', 'large.txt')
    git('commit', '-qm', 'initial native registry fixture')
    git('remote', 'add', 'origin', endpoint)
    assert token not in (repo / '.git/config').read_bytes()
    git('push', '--porcelain', 'origin', 'main')
    clone = root / 'git-clone'
    git('clone', endpoint, str(clone))
    assert (clone / 'large.txt').read_bytes() == source
    assert git('-C', str(clone), 'symbolic-ref', 'HEAD').strip() == b'refs/heads/main'
    first = git('rev-parse', 'HEAD').strip()
    status, advertisement = request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-receive-pack', headers=headers)
    assert status == 200 and first + b' refs/heads/main\0' in advertisement, advertisement
    git('tag', 'v1')
    git('push', '--atomic', 'origin', 'refs/tags/v1')
    git('push', 'origin', ':refs/tags/v1')
    (repo / 'extra.lucb').write_text('pub let value = 42\n')
    (repo / 'large.txt').write_bytes(source[:100000] + b'changed line\n' + source[100000:])
    git('add', 'extra.lucb', 'large.txt')
    git('commit', '-qm', 'incremental history')
    latest = git('rev-parse', 'HEAD').strip()
    thin = git('pack-objects', '--stdout', '--thin', '--revs', input=latest + b'\n^' + first + b'\n')
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
    command = b'0' * 40 + b' ' + latest + b' refs/heads/thin\0 report-status atomic'
    wire = f'{len(command) + 4:04x}'.encode() + command + b'0000' + thin
    status, report = transfer(port, 'POST', '/git/testuser/git-wire/git-receive-pack', wire,
                              {**headers, 'Content-Type': 'application/x-git-receive-pack-request'})
    assert status == 200 and b'ok refs/heads/thin\n' in report, report
    git('push', 'origin', 'main')
    git('-C', str(clone), 'fetch', 'origin')
    git('-C', str(clone), 'merge', '--ff-only', 'origin/main')
    assert git('-C', str(clone), 'rev-parse', 'HEAD').strip() == latest
    assert (clone / 'large.txt').read_bytes() == (repo / 'large.txt').read_bytes()
    git('tag', '-a', 'annotated', '-m', 'native annotated fixture')
    git('push', 'origin', 'refs/tags/annotated')
    remote = git('ls-remote', 'origin')
    assert latest + b'\trefs/tags/annotated^{}' in remote
    git('-C', str(clone), 'fetch', '--tags', 'origin')
    assert git('-C', str(clone), 'rev-parse', 'annotated^{}').strip() == latest
    # Annotated tag of a blob: its peeled target is not an advertised ref tip.
    blob = git('hash-object', '-w', '--stdin', input=b'tag-only blob\n').strip()
    git('tag', '-a', 'blob-tag', blob.decode(), '-m', 'blob tag fixture')
    git('tag', '-a', 'nested-tag', 'blob-tag', '-m', 'nested tag fixture')
    git('push', 'origin', 'refs/tags/blob-tag', 'refs/tags/nested-tag')
    remote = git('ls-remote', 'origin')
    assert blob + b'\trefs/tags/blob-tag^{}' in remote
    assert blob + b'\trefs/tags/nested-tag^{}' in remote
    want_blob = b'want ' + blob + b'\n'
    request_blob = f'{len(want_blob) + 4:04x}'.encode() + want_blob + b'00000009done\n'
    status, packed_blob = transfer(port, 'POST', '/git/testuser/git-wire/git-upload-pack', request_blob,
                                  {**headers, 'Content-Type': 'application/x-git-upload-pack-request'})
    assert status == 200 and packed_blob.startswith(b'0008NAK\nPACK'), packed_blob[:80]
    git('-C', str(clone), 'index-pack', '--stdin', '--strict', input=packed_blob[8:])
    assert git('-C', str(clone), 'cat-file', 'blob', blob.decode()) == b'tag-only blob\n'
    git('-C', str(clone), 'fetch', '--tags', 'origin')
    git('-C', str(clone), 'fsck', '--strict')
    git('push', '--atomic', 'origin', 'HEAD:refs/heads/z', 'HEAD:refs/heads/a')
    status, advertisement = request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-receive-pack', headers=headers)
    assert status == 200
    assert advertisement.index(b' refs/heads/a') < advertisement.index(b' refs/heads/main') < advertisement.index(b' refs/heads/z')
    packet = b'0' * 40 + b' ' + b'f' * 40 + b' refs/heads/rejected\0 report-status atomic'
    pack_head = b'PACK\0\0\0\2\0\0\0\0'
    broken_graph = f'{len(packet) + 4:04x}'.encode() + packet + b'0000' + pack_head + hashlib.sha1(pack_head).digest()
    status, report = transfer(port, 'POST', '/git/testuser/git-wire/git-receive-pack', broken_graph,
                              {**headers, 'Content-Type': 'application/x-git-receive-pack-request'})
    assert status == 200 and b'ng refs/heads/rejected transaction rejected\n' in report, report
    status, advertisement = request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-receive-pack', headers=headers)
    assert status == 200 and b'refs/heads/rejected' not in advertisement
    assert latest + b' refs/heads/main' in advertisement
    # Wrong Content-Type and malformed framing must not mutate refs.
    assert request(port, 'POST', '/git/testuser/git-wire/git-receive-pack', headers=headers)[0] == 415
    assert request(port, 'POST', '/git/testuser/git-wire/git-receive-pack',
                   headers={**headers, 'Content-Type': 'application/x-git-receive-pack-request'})[0] == 400
    git('push', '--porcelain', 'origin', 'main')  # Up-to-date discovery succeeds.
    fetch_path = '/git/testuser/git-wire/git-upload-pack'
    want = b'want ' + b'f' * 40 + b'\n'
    wire = f'{len(want) + 4:04x}'.encode() + want + b'00000009done\n'
    status, _ = transfer(port, 'POST', fetch_path, wire,
                         {**headers, 'Content-Type': 'application/x-git-upload-pack-request'})
    assert status == 403
    # Everything is public: discovery and a complete clone need no credential at all,
    # while a push without one is still refused.
    assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-upload-pack')[0] == 200
    assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-receive-pack')[0] == 401
    anonymous_env = {key: value for key, value in env.items() if key not in ('GIT_ASKPASS', 'LUCE_GIT_TOKEN', 'LUCE_GIT_USERNAME')}
    anonymous = root / 'git-anonymous-clone'
    subprocess.run(['git', 'clone', '-q', endpoint, str(anonymous)], env=anonymous_env, check=True, capture_output=True, timeout=90)
    assert (anonymous / 'large.txt').read_bytes() == (repo / 'large.txt').read_bytes()
    subprocess.run(['git', '-C', str(anonymous), 'fsck', '--strict'], env=anonymous_env, check=True, capture_output=True, timeout=90)
    refused = subprocess.run(['git', '-C', str(anonymous), 'push', 'origin', 'HEAD:refs/heads/anonymous'], env=anonymous_env, capture_output=True, timeout=90)
    assert refused.returncode != 0
    assert request(port, 'POST', fetch_path, headers=headers)[0] == 415
    assert request(port, 'POST', fetch_path, headers={**headers, 'Content-Type': 'application/x-git-upload-pack-request'})[0] == 400
    # A version tag publishes a static, history-free release; main is left untouched.
    site = root / 'site' / 'testuser' / 'git-wire'
    git('checkout', '-q', '-b', 'release-line')
    (repo / 'package.prisma').write_text('#prisma 4.0\ndef package "git-wire" {\n    str owner = "testuser"\n'
        '    str version = "1.3.0"\n    str kind = "package"\n    str language = "luce-base"\n    str description = "Release fixture"\n}\n')
    git('add', 'package.prisma')
    git('commit', '-qm', 'declare package 1.3.0')
    released = git('rev-parse', 'HEAD').strip().decode()
    git('push', 'origin', 'release-line')
    git('tag', '-a', 'v9.9.9', '-m', 'wrong version')
    rejected = subprocess.run(['git', '-C', str(repo), 'push', 'origin', 'v9.9.9'], env=env, capture_output=True, timeout=90)
    assert rejected.returncode != 0 and b'version must match the release tag' in rejected.stderr, rejected.stderr
    assert not site.exists()
    # Release notes are mandatory: a lightweight tag and an empty message are refused.
    git('tag', 'v1.3.0')
    bare = subprocess.run(['git', '-C', str(repo), 'push', 'origin', 'v1.3.0'], env=env, capture_output=True, timeout=90)
    assert bare.returncode != 0 and b'release notes are required' in bare.stderr, bare.stderr
    git('tag', '-d', 'v1.3.0')
    assert not site.exists()
    git('tag', '-a', 'v1.3.0', '-m', 'First fixture release.\n\n- adds <package.prisma>\n')
    git('push', 'origin', 'v1.3.0')
    assert (site / '1.3.0.notes').read_text() == 'First fixture release.\n\n- adds <package.prisma>'
    pack = (site / '1.3.0.pack').read_bytes()
    assert (site / '1.3.0.prisma').read_bytes() == (repo / 'package.prisma').read_bytes()
    assert (site / 'versions').read_text() == f'1.3.0 {hashlib.sha256(pack).hexdigest()} {released}\n'
    assert (root / 'site' / 'index').read_text() == 'testuser/git-wire\t1.3.0\tRelease fixture\tpackage\n'
    front = (root / 'site' / 'index.html').read_text()
    assert '<a class="card" href="/testuser/git-wire/">' in front and 'Release fixture' in front
    assert 'Find, install and publish Luce packages' in front and '0 applications &middot; 0 tools &middot; 1 package</p>' in front and '<a href="/tools/">Tools</a>' in front and '<section class="kind" id="packages">' in front and '<a href="/applications/">Applications</a>' in front
    assert '<a class="here" href="/packages/">Packages</a>' in (root / 'site' / 'packages' / 'index.html').read_text()
    assert True and 'id="applications"' not in front
    detail = (site / 'index.html').read_text()
    assert '<h1>testuser/git-wire</h1>' in detail and 'luc add testuser/git-wire' in detail
    assert hashlib.sha256(pack).hexdigest() in detail and released[:12] in detail
    assert 'First fixture release.' in detail and '- adds &lt;package.prisma&gt;' in detail
    listing = (site / '1.3.0/tree/index.html').read_text()
    assert '/testuser/git-wire/1.3.0/blob/package.prisma.html' in listing and 'large.txt' in listing
    source = (site / '1.3.0/blob/main.lucb.html').read_text()
    assert '<span class="l" id="L1"><span class="k">pub</span> <span class="k">func</span> <span class="d">main</span>() -&gt; <span class="t">i32</span>:</span>' in source and 'id="L2"' in source
    unpacked = root / 'release-unpacked'
    subprocess.run(['git', 'init', '-q', str(unpacked)], env=env, check=True, timeout=30)
    subprocess.run(['git', '-C', str(unpacked), 'unpack-objects'], input=pack, env=env, check=True, capture_output=True, timeout=30)
    listed = subprocess.check_output(['git', '-C', str(unpacked), 'ls-tree', '-r', '--name-only', released], env=env, timeout=30)
    assert b'package.prisma' in listed.split() and b'large.txt' in listed.split()
    parents = subprocess.check_output(['git', '-C', str(unpacked), 'cat-file', '-p', released], env=env, timeout=30)
    missing = subprocess.run(['git', '-C', str(unpacked), 'cat-file', '-e', parents.split(b'parent ')[1][:40].decode()], env=env, capture_output=True, timeout=30)
    assert missing.returncode != 0, 'a release pack carries no history'
    for refusal in (('push', '--force', 'origin', 'main:refs/tags/v1.3.0'), ('push', 'origin', ':refs/tags/v1.3.0')):
        refused = subprocess.run(['git', '-C', str(repo), *refusal], env=env, capture_output=True, timeout=90)
        assert refused.returncode != 0 and b'cannot be moved or deleted' in refused.stderr, refused.stderr
    git('checkout', '-q', 'main')
    print('PASS version tag publishes an immutable static release; mismatched, moved and deleted tags are refused', flush=True)
    print('PASS stock Git clone, default main HEAD, incremental fetch, annotated tags and strict fsck', flush=True)
    print('PASS stock Git HTTP initial/incremental push, sorted discovery, atomic refs, deletion and failure report', flush=True)
    return latest
