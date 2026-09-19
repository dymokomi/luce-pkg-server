"""Private Git object transport tests; Python hashing is only an independent oracle."""
import hashlib
import http.client
from pathlib import Path


def wire(payload):
    return b'blob ' + str(len(payload)).encode() + b'\0' + payload


def transfer(port, method, path, body=b'', headers=None, chunked=False):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=90)
    try:
        value = [body[:7], body[7:]] if chunked else body
        connection.request(method, path, value, headers or {}, encode_chunked=chunked)
        response = connection.getresponse()
        result = response.status, response.read()
        assert response.getheader('Cache-Control') == 'no-store', (result[0], result[1][:200], response.getheaders())
        return result
    finally:
        connection.close()


def check(port, headers, other_headers):
    root = '/v1/repositories/testuser/demo/objects/'
    data = wire(b'binary\0\xffobject')
    identity = hashlib.sha1(data).hexdigest()
    endpoint = root + identity
    for method in ('GET', 'PUT'):
        assert transfer(port, method, endpoint, data)[0] == 401
        assert transfer(port, method, endpoint, data, {'X-Forwarded-User': 'testuser'})[0] == 401
        assert transfer(port, method, endpoint, data, other_headers)[0] == 403
    assert transfer(port, 'GET', endpoint, headers=headers)[0] == 404
    for bad in (b'blob 1\0too long', b'unknown 0\0', wire(b'wrong id'), b''):
        assert transfer(port, 'PUT', endpoint, bad, headers)[0] == 400
        assert transfer(port, 'GET', endpoint, headers=headers)[0] == 404
    assert transfer(port, 'PUT', root + 'bad-id', data, headers)[0] == 400
    assert transfer(port, 'PUT', endpoint, data, headers, chunked=True) == (200, identity.encode())
    assert transfer(port, 'PUT', endpoint, data, headers) == (200, identity.encode())
    assert transfer(port, 'GET', endpoint, headers=headers) == (200, data)
    source = Path(__file__).resolve().parents[2] / 'luce-base/bootstrap/luce-base-arm64-macos.c'
    large = wire(source.read_bytes())
    assert len(large) > 1048576
    large_id = hashlib.sha1(large).hexdigest()
    assert transfer(port, 'PUT', root + large_id, large, headers) == (200, large_id.encode())
    assert transfer(port, 'GET', root + large_id, headers=headers) == (200, large)
    assert transfer(port, 'PUT', root + large_id, large, headers) == (200, large_id.encode())
    print('PASS object HTTP auth, ownership, invalid/no-write, chunked upload, idempotence and real bootstrap', flush=True)
    return root + large_id, large
