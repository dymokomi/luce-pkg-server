# Frozen v1 contracts

Owner decisions and inspections recorded 2026-09-16. These freeze filenames,
encodings and operational boundaries. They do not complete independent review,
real-credential custody or `pkg.luciaos.com` deployment.

## Manifests and locks

- Compilers continue to read **`luce.toml`**. YAML is not a v1 target.
- The lockfile is **`luce.lock`**, TOML, `schema_version = 1`. Compilers do not
  read it. Only `luc` / `luce-pkg` write and consume it.
- Dual `luce.toml` + `luce.yaml` in one project is an error, not a migration pair.
- Lock entries bind registry origin, package coordinate, version, canonical
  source digest (SHA-256), Git object format/commit when sourced from Git,
  compiler package identity, and toolchain constraints.

## Git object format

- Hosted repositories speak ordinary **SHA-1** Git for v1 stock-Git compatibility.
- SHA-1 is forbidden for account secrets, vault keys, release signatures and
  lock digests. Those use SHA-256 and ML-DSA-65.
- Collision defense: reject the known SHAttered colliding PDF prefixes; reject
  inserting two distinct byte-strings that hash to one object ID; never silently
  alias SHA-1 and SHA-256 object IDs.
- SHA-256 Git is a later advertised capability, not implied by SHA-256 releases.

## Application identity records

Binary little-endian, exact EOF, not high-level object serialization.

Shared header: `"LID1"` | u8 kind | u16 payload_length | payload.

| kind | name | payload |
| --- | --- | --- |
| 1 | invite | u8 flags, u32 expiry_unix, u16 code_len, code UTF-8, u8 role, 32-byte nonce |
| 2 | user | u16 handle_len, handle, 32-byte user_id, u8 role, u8 status |
| 3 | device | 32-byte user_id, 32-byte device_id, ML-DSA-65 public key, u64 created |
| 4 | vault | u8 kdf=1 (Argon2id v0x13), u32 m_kib, u32 t, u8 p, 16-byte salt, XChaCha20-Poly1305 sealed inner |
| 5 | token | 32-byte token_id, 32-byte user_id, u32 scope, u64 expiry, 32-byte repo_id or zero |
| 6 | recovery | 32-byte user_id, Argon2id-wrapped ML-DSA-65 seed, shown once |

Invites are single-use. Tokens are stored as SHA-256 digests of the secret, never
the secret. Vault inner plaintext is identity seeds plus key-role metadata and is
authenticated as associated data with the vault header.

Uncalibrated starting Argon2id vault costs: m=65536 KiB, t=3, p=1. These are not
production-calibrated.

## Release signatures

- Publisher and registry-root signatures: **ML-DSA-65** over a canonical
  `"LRS1"` metadata encoding (schema, origin, package, version, commit, SHA-256
  source digest, toolchain).
- Freshness: root metadata expires; clients reject rollback to older timestamps
  for the same role. Exact TUF compatibility is not claimed.
- No algorithm downgrade.

## HTTPS proxy boundary

Inspected 2026-09-16 on the existing host, read-only:

- Public HTTPS is terminated by Caddy on :443 with Let's Encrypt certificates.
- Application backends already used by other sites bind loopback only
  (`127.0.0.1`). `pkg.luciaos.com` has **no site block yet**.
- Identity is never taken from `X-Forwarded-For` or the proxy source IP. The
  package server authenticates invitations, sessions and tokens itself.
- Git routes must preserve method, path/query, `Authorization`, Git content
  types and `Git-Protocol`. Do not HTML-rewrite Git bodies. Do not cache
  authenticated discovery or Git service responses.
- Client TLS for `luc` is a separate M3b Base HTTPS implementation. Locate of
  historical `luce-tls` under this owner found **no repository**; M3b starts a
  new package rather than resuming a hidden checkpoint.

## Independent review

Crypto, storage and protocol reviews remain gates before real credentials. This
document does not satisfy them.
