# Frozen v1 contracts

Owner decisions and inspections recorded 2026-09-16 and revised 2026-09-20. These freeze filenames,
encodings and operational boundaries. They do not complete independent review,
real-credential custody or `pkg.luciaos.com` deployment.

Owner confirmations, September 19, 2026: account and package-release signatures
remain **ML-DSA-65**; password-protected local credential vaults use **Argon2id +
XChaCha20-Poly1305**, implemented in Luce Base. No initial Ed25519 or AES-GCM
substitution. These are application-crypto choices, not changes to HTTP/TLS.
The replacement Prism-backed authority does not by itself implement the complete
account-key/vault contract below; integration and verification remain required.

## Visibility and accounts

Owner decision, September 21, 2026:

- Every repository, package and release on `pkg.luciaos.com` is **public**. There
  is no private package, no visibility flag and no per-reader ACL.
- Browsing, search, Git clone/fetch, version listing, release download and
  `luc` installation require **no account and no credential**.
- An account is required only for operations that change state: repository
  creation, Git push, pull-request creation and state changes, signing-key
  enrollment and release publication. Registration stays invite-only.
- `dymokomi` is the only account for now. Collaborator roles remain later work.
- A release is a pushed tag `v<major.minor.patch>` whose commit carries a root
  `package.prisma` naming this owner, this repository and this version. The
  registry publishes it as static files (a history-free Git pack, the package
  definition, a per-package `versions` listing with SHA-256 digests, and a global
  `index`). Released tags cannot be moved or deleted. The tag must be annotated:
  its message is the mandatory release notes.
- Integrity is the SHA-256 recorded in `luc.lock` plus HTTPS. Publisher
  signatures, signing-key enrollment and the separate publish protocol are
  dropped; they may return later as an additional file without changing this model.
- Nothing has been released and there is one user, so no format, command or
  protocol is kept for backward compatibility. Old ones are replaced outright.

## Package documents, recipes and locks

- The authored package definition is **`package.prisma`**, schema
  `luc.package/1`. It declares identity, requirements, named outcomes, targets,
  resources, recipes and requested permissions.
- Optional installation/build logic is high-level Luce in **`install.luc`**,
  referenced by `package.prisma`; source is not embedded in the Prism document.
- The generated lockfile remains **`luc.lock`**, but its content is canonical
  Prism text under `luc.lock/1`. Compilers do not read it. Only `luc` / `luce-pkg`
  write and consume it.
- This September 20 decision supersedes the September 19 `luce.toml` plus TOML
  `luc.lock` target. Existing TOML projects are read-only migration inputs.
- Current compilers may continue to read `luce.toml`; `luc` generates it privately
  as an adapter from the resolved Prism graph. It is not a second authored model.
- Lock entries bind registry origin, package coordinate, version, canonical source
  digest, Git object format/commit, compiler/toolchain identity, sandbox policy,
  complete outcome graph and every externally referenced file digest.
- `install.luc` runs only through `luce run --sandbox ROOT`. It is interpreted,
  cannot import Luce Base directly or transitively, and returns a bounded Prism
  plan. `luc` performs staged installation and receipt-based uninstall.

## Git object format

- Hosted repositories speak ordinary **SHA-1** Git for v1 stock-Git compatibility.
- SHA-1 is forbidden for account secrets, vault keys, release signatures and
  lock digests. Those use SHA-256 and ML-DSA-65.
- Collision defense: reject the known SHAttered colliding PDF prefixes; reject
  inserting two distinct byte-strings that hash to one object ID; never silently
  alias SHA-1 and SHA-256 object IDs.
- SHA-256 Git is a later advertised capability, not implied by SHA-256 releases.

## Pull requests without forks

- v1 pull requests reference two `refs/heads/*` branches in the same repository.
  Short branch names are stored; `refs/`-prefixed inputs are rejected.
- There is no fork object, fork API, implicit repository copy, or cross-repository
  source. Ordinary Git owns commits, branches, pushes and merges.
- Creation captures base/head commit IDs atomically and assigns a monotonic local
  number. One open record per exact base/head pair is allowed.
- States are `open`, `closed`, and terminal `merged`. A merged transition is only
  recorded after the current base commit is proven to contain the current head by
  a bounded native commit-ancestry walk. The server does not create merge commits.
- Current repository ACLs remain owner-only. Collaborator permissions are a later
  prerequisite for PR authors other than the owner; review APIs do not widen Git
  read/write access.

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

- Publisher signatures: **ML-DSA-65** over canonical `LRS1` legacy metadata or
  dependency-aware `LRS2` metadata. LRS2 binds origin, package coordinate,
  version, commit, SHA-256 source digest, compiler/toolchain, compiler package
  identity and the sorted dependency requirements. Publication also verifies
  those LRS2 identity/dependency fields against the signed commit's root package
  document. The next release-record revision must bind canonical `package.prisma`,
  named outcomes, permissions and every referenced file including `install.luc`;
  LRS2 remains a legacy implemented input during migration.
- Registry-root signature encoding and freshness/rotation policy remain a
  separate design and review gate.
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
