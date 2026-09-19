"""Real stock Git client against native HTTP receive-pack; no runtime Git dependency."""
import os
from pathlib import Path
import subprocess
import hashlib
import struct
import zlib
from object_http import transfer


def check(port, headers, root, request):
    assert request(port, 'POST', '/v1/repositories', {'name': 'git-wire'}, headers)[0] == 201
    endpoint = f'http://127.0.0.1:{port}/git/testuser/git-wire'
    assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=git-receive-pack')[0] == 401
    assert request(port, 'GET', '/git/testadmin/git-wire/info/refs?service=git-receive-pack', headers=headers)[0] == 403
    assert request(port, 'GET', '/git/testuser/git-wire/info/refs?service=bad', headers=headers)[0] == 403
    assert request(port, 'HEAD', '/git/testuser/git-wire/info/refs?service=git-receive-pack', headers=headers) == (200, b'')
    repo = root / 'git-client'
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.test',
               GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.test',
               GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.extraHeader',
               GIT_CONFIG_VALUE_0='Authorization: ' + headers['Authorization'],
               GIT_TRACE_PACKET='1')

    def git(*args, success=True, input=None):
        result = subprocess.run(['git', '-C', str(repo), *args], env=env,
                                input=input, capture_output=True, timeout=90)
        if success: assert result.returncode == 0, (args, result.stderr)
        else: assert result.returncode != 0, args
        return result.stdout

    repo.mkdir()
    git('init', '--object-format=sha1', '-b', 'main', '-q')
    (repo / 'main.lucb').write_text('pub func main() -> i32:\n    return 0\n')
    # Large near-identical revisions force stock Git to use a remote delta base.
    source = b''.join(hashlib.sha256(str(i).encode()).hexdigest().encode() + b'\n' for i in range(4096))
    (repo / 'large.txt').write_bytes(source)
    git('add', 'main.lucb', 'large.txt')
    git('commit', '-qm', 'initial native registry fixture')
    git('remote', 'add', 'origin', endpoint)
    git('push', '--porcelain', 'origin', 'main')
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
    print('PASS stock Git HTTP initial/incremental push, sorted discovery, atomic refs, deletion and failure report', flush=True)
    return latest
