"""Account proof is produced by native Luce Base, not a Python crypto wrapper."""
import concurrent.futures
import subprocess
from object_http import transfer

CHALLENGE = '/v1/identity/key-challenge'
ENROLL = '/v1/identity/key'
ORIGIN = 'https://registry.example.test'


def check(port, headers, other_headers, fixture):
    def call(path, body=b'', auth=headers):
        return transfer(port, 'POST', path, body, auth)

    def proof(nonce, origin=ORIGIN, account='testuser'):
        return bytes.fromhex(subprocess.check_output(
            [str(fixture), 'proof', origin, account, nonce.hex()],
            text=True, timeout=30).strip())

    assert call(CHALLENGE, auth={})[0] == 401
    assert call(ENROLL, auth={})[0] == 401
    assert call(CHALLENGE, b'x')[0] == 400
    status, nonce = call(CHALLENGE)
    assert status == 200 and len(nonce) == 32
    encoded = proof(nonce)
    assert len(encoded) == 5261
    assert call(ENROLL, encoded)[0] == 415
    binary = dict(headers, **{'Content-Type': 'application/octet-stream'})
    for malformed in (b'', encoded[:-1], encoded + b'x'):
        assert call(ENROLL, malformed, binary)[0] == 400
    # A caller's Host/Forwarded headers must not choose the signed origin.
    hostile = dict(binary, Host='attacker.invalid', **{'X-Forwarded-Host': 'attacker.invalid'})
    assert call(ENROLL, proof(nonce, 'https://attacker.invalid'), hostile)[0] == 400
    assert call(ENROLL, proof(nonce, account='testadmin'), binary)[0] == 400
    mutated = bytearray(encoded)
    mutated[-1] ^= 1
    assert call(ENROLL, bytes(mutated), binary)[0] == 400
    status, replacement = call(CHALLENGE)
    assert status == 200 and len(replacement) == 32 and nonce != replacement
    assert call(ENROLL, encoded, binary)[0] == 400
    encoded = proof(replacement)
    # Another authenticated account cannot redeem this account's proof.
    assert call(ENROLL, encoded, dict(other_headers, **{'Content-Type': 'application/octet-stream'}))[0] == 400
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: call(ENROLL, encoded, hostile)[0], range(2)))
    assert sorted(results) == [201, 409], results
    assert call(ENROLL, encoded, binary)[0] == 409
    assert call(CHALLENGE)[0] == 409
    print('PASS native account-key HTTP enrollment, origin binding, replacement and replay', flush=True)


def persisted(port, headers):
    assert transfer(port, 'POST', CHALLENGE, headers=headers)[0] == 409
