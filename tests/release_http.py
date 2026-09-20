"""Signed release HTTP oracle. Stock Git builds packs; native Luce signs metadata."""
import concurrent.futures
import os
import subprocess
from object_http import transfer
from key_http import ORIGIN

ROOT = '/v1/releases/testuser/git-wire'

def catalog(wire):
    assert wire[:4] == b'LPV1' and len(wire) >= 6
    count, at, versions = int.from_bytes(wire[4:6], 'little'), 6, []
    for _ in range(count):
        size = wire[at]
        at += 1
        versions.append(wire[at:at + size].decode())
        at += size
    assert at == len(wire)
    return versions


def check(port, headers, other_headers, root, fixture, commit):
    source = subprocess.check_output(['git', '-C', str(root / 'git-client'), 'pack-objects', '--stdout', '--revs'],
                                     input=commit + b'\n', timeout=30)
    pack = root / 'release-source.pack'
    pack.write_bytes(source)
    def signed(version='1.2.3', origin=ORIGIN, package='testuser/git-wire', target=commit):
        subprocess.run([str(fixture), 'release', origin, package, version, target.decode(), str(pack), str(root)],
                       check=True, timeout=30)
        metadata = (root / 'release-metadata').read_bytes()
        signature = (root / 'release-signature').read_bytes()
        key = (root / 'release-key').read_bytes()
        wire = b'LRP1' + len(metadata).to_bytes(2, 'little') + b'\0\0' + metadata + signature + pack.read_bytes()
        return wire, {'metadata': metadata, 'signature': signature, 'publisher_key': key, 'source': pack.read_bytes()}

    wire, expected = signed()
    binary = dict(headers, **{'Content-Type': 'application/octet-stream'})
    assert transfer(port, 'GET', ROOT)[0] == 401
    assert transfer(port, 'GET', ROOT, headers=other_headers)[0] == 403
    assert catalog(transfer(port, 'GET', ROOT, headers=headers)[1]) == []
    invalid_signature = bytearray(wire)
    invalid_signature[8 + len(expected['metadata'])] ^= 1
    assert transfer(port, 'POST', ROOT, bytes(invalid_signature), binary)[0] == 400
    assert transfer(port, 'POST', ROOT, wire)[0] == 401
    assert transfer(port, 'POST', ROOT, wire, other_headers)[0] == 403
    assert transfer(port, 'POST', ROOT, wire, headers)[0] == 415
    assert transfer(port, 'POST', '/v1/releases/testadmin/demo', wire,
                    dict(other_headers, **{'Content-Type': 'application/octet-stream'}))[0] == 409
    for invalid in (b'', b'LRP1', wire[:3300], b'BAD!' + wire[4:], wire[:6] + b'\1\0' + wire[8:],
                    wire[:4] + b'\xff\xff' + wire[6:], wire[:-1], wire + b'extra'):
        assert transfer(port, 'POST', ROOT, invalid, binary)[0] == 400
        assert transfer(port, 'GET', ROOT + '/1.2.3/source', headers=headers)[0] == 404
    for origin, package, target in (('https://attacker.invalid', 'testuser/git-wire', commit),
                                    (ORIGIN, 'testadmin/git-wire', commit),
                                    (ORIGIN, 'testuser/git-wire', b'1' * 40)):
        bad, _ = signed(origin=origin, package=package, target=target)
        assert transfer(port, 'POST', ROOT, bad, binary)[0] in (400, 404)
    wire, expected = signed()
    hostile = dict(binary, Host='attacker.invalid', **{'X-Forwarded-Host': 'attacker.invalid'})
    assert transfer(port, 'POST', ROOT, wire, hostile, chunked=True) == (201, b'published')
    assert transfer(port, 'POST', ROOT, wire, binary) == (200, b'unchanged')
    assert catalog(transfer(port, 'GET', ROOT, headers=headers)[1]) == ['1.2.3']
    persisted(port, headers, expected)
    assert transfer(port, 'GET', ROOT + '/1.2.3/source')[0] == 401
    assert transfer(port, 'GET', ROOT + '/1.2.3/source', headers=other_headers)[0] == 403
    for suffix in ('1.2.3/unknown', '30000000000000000000.0.0/source', '01.2.3/source'):
        assert transfer(port, 'GET', ROOT + '/' + suffix, headers=headers)[0] == 400
    # Same version, different correctly signed bytes is not a replacement.
    changed, _ = signed(target=b'1' * 40)
    assert transfer(port, 'POST', ROOT, changed, binary)[0] in (400, 404)
    # Two independent requests for a new version can publish it only once.
    raced, _ = signed(version='1.2.4')
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: transfer(port, 'POST', ROOT, raced, binary)[0], range(2)))
    assert statuses.count(201) == 1 and all(s in (200, 201, 409) for s in statuses), statuses
    assert catalog(transfer(port, 'GET', ROOT, headers=headers)[1]) == ['1.2.4', '1.2.3']
    # Force body spooling and chunked source storage with an extra valid Git blob.
    large = os.urandom(1100000)
    blob = subprocess.check_output(['git', '-C', str(root / 'git-client'), 'hash-object', '-w', '--stdin'], input=large, timeout=30).strip()
    large_pack = subprocess.check_output(['git', '-C', str(root / 'git-client'), 'pack-objects', '--stdout', '--revs'],
                                         input=commit + b'\n' + blob + b'\n', timeout=30)
    assert len(large_pack) > 1048576
    pack.write_bytes(large_pack)
    conflicting, _ = signed()
    assert transfer(port, 'POST', ROOT, conflicting, binary) == (409, b'release conflict')
    persisted(port, headers, expected)
    large_wire, large_expected = signed(version='1.2.5')
    assert transfer(port, 'POST', ROOT, large_wire, binary) == (201, b'published')
    assert catalog(transfer(port, 'GET', ROOT, headers=headers)[1]) == ['1.2.5', '1.2.4', '1.2.3']
    persisted(port, headers, large_expected, '1.2.5')
    print('PASS signed release HTTP: native proof, framing, ownership, retries, races and spooled/chunked source', flush=True)
    return expected, large_expected


def persisted(port, headers, expected, version='1.2.3'):
    for part, contents in expected.items():
        assert transfer(port, 'GET', ROOT + '/' + version + '/' + part, headers=headers) == (200, contents)
