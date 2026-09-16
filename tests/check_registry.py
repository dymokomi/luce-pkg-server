#!/usr/bin/env python3
"""Exercise the loopback invite API and trusted-proxy contract."""
import http.client
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def encode_invite(code: str, role=2, expiry=2000000000, flags=0, nonce=None):
    nonce = nonce or bytes(range(32))
    payload = struct.pack("<B I H", flags, expiry, len(code)) + code.encode() + bytes([role]) + nonce
    return b"LID1" + bytes([1]) + struct.pack("<H", len(payload)) + payload


def request(port, method, path, body=b"", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    payload = response.read()
    conn.close()
    return response.status, payload


def main():
    binary = Path(sys.argv[1])
    with tempfile.TemporaryDirectory(prefix="luce-registry-") as tmp:
        db = Path(tmp) / "registry.db"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        process = subprocess.Popen([binary, str(db), str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    out = process.stdout.read()
                    raise SystemExit(f"registry exited early: {process.returncode} {out}")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise SystemExit("registry did not accept connections")
            status, body = request(port, "GET", "/health")
            assert status == 200 and body == b"ok", (status, body)
            status, body = request(port, "GET", "/v1/identity", headers={
                "Authorization": "Bearer secret",
                "X-Forwarded-For": "8.8.8.8",
                "Git-Protocol": "version=2",
            })
            text = body.decode()
            assert status == 200, (status, text)
            assert "identity=untrusted-proxy" in text
            assert "authorization=Bearer secret" in text
            assert "forwarded=8.8.8.8" in text
            assert "git-protocol=version=2" in text
            assert "8.8.8.8" not in text.split("identity=", 1)[1].split("\n", 1)[0]
            invite = encode_invite("invite-one")
            status, body = request(port, "POST", "/v1/invites/redeem", invite)
            assert status == 201 and body == b"registered", (status, body)
            status, body = request(port, "POST", "/v1/invites/redeem", invite)
            assert status == 409 and body == b"invite-used", (status, body)
            status, body = request(port, "POST", "/v1/invites/redeem", b"nope")
            assert status == 400, (status, body)
            print("PASS registry health, untrusted proxy identity and single-use invite", flush=True)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
