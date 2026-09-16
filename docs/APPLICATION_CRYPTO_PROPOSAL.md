# Application cryptography — accepted v1 profile

Owner decisions recorded 2026-09-15. These freeze algorithm families for
account/device/publisher/root signatures and local vault encryption. They do not
complete M0 encodings, M1b review, vault cost calibration, or real-credential
custody. HTTP behind the existing HTTPS proxy remains the accepted transport.

## Accepted choices

Application signatures use **ML-DSA-65** in Luce Base, specified by
[NIST FIPS 204](https://csrc.nist.gov/pubs/fips/204/final). This keeps the
post-quantum application-identity direction. It is independent of HTTPS/Caddy and
is not a claim that a Base implementation already exists or is security-reviewed.
Kinogaki Ed25519 identities remain unlinkable without an explicit signed linking
ceremony.

Password-protected local vaults use **Argon2id + XChaCha20-Poly1305**. Argon2id
v0x13 is implemented in `luce-crypto`; cost calibration and the vault format
remain separate work. XChaCha20-Poly1305 uses an extended 192-bit nonce. Its
implementation-oriented reference is the
[Libsodium construction](https://libsodium.gitbook.io/doc/secret-key_cryptography/aead/chacha20-poly1305/xchacha20-poly1305_construction),
with core ChaCha20/Poly1305 definitions and vectors in
[RFC 8439](https://www.rfc-editor.org/rfc/rfc8439.html). Do not substitute RFC
8439's shorter nonce. AES-256-GCM was the declined alternative.

v1 package manifests remain compiler-compatible **`luce.toml`**. `luc` reads and
writes that format. A YAML migration is not a v1 target. The lockfile
filename/encoding is still unfrozen and is a later M0 item, not a silent
companion of this decision.

Kinogaki's inspected `Key.h`/`Seal.h` use Ed25519 signatures and
XChaCha20-Poly1305 content encryption through C++. That is
architectural/algorithm reference only: no existing key, credential record, realm
identity or C++ engine is imported. A similar cipher does not make the two
vault/account formats interchangeable.

## Implementation consequences

1. ML-DSA-65 needs native SHAKE/Keccak, bounded polynomial arithmetic/sampling,
   exact FIPS encodings, key generation/sign/verify, entropy failure handling,
   official and independent vectors, malformed encodings and generated-code review.
   Recheck FIPS 204's published errata before coding; the current NIST landing
   page points to a July 31, 2026 potential-updates list. Experimental SHAKE128/256
   and ML-DSA-65 keygen/sign/verify now exist in `luce-crypto`; they are not
   reviewed or approved for real credentials.
2. XChaCha20-Poly1305 needs native ChaCha20/HChaCha20/Poly1305, exact AEAD framing,
   nonce/counter/size bounds and verify-before-release decryption. Tests must reject
   altered ciphertext/tag/nonce/associated data without exposing unauthenticated
   plaintext, and cover allocation/entropy/cancellation/ownership failures.
   Experimental IETF ChaCha20-Poly1305 and XChaCha20-Poly1305 now exist in
   `luce-crypto`.
3. `luce-auth` still needs separately versioned vault, key, proof, challenge,
   invite and token records. Authenticate vault format/cost/key-role metadata;
   generate identity keys randomly and rewrap them on password change. Freeze
   canonical signature inputs, domain separation and recovery/rotation behavior.
4. `luce-pkg` still needs publisher versus registry/root roles, exact signed release
   metadata, freshness/rollback policy and independently bootstrapped trust. An
   algorithm choice alone does not implement TUF compatibility or release trust.

No automatic algorithm downgrade, mixed profile or improvised hybrid is authorized.
TLS-client algorithms are selected independently from proxy interoperability.

All algorithm internals remain Base; foreign engines may be pinned **test-only**
oracles. Private signing/vault keys are never copied into public fixtures/logs.
Independent cryptographic/protocol review and real-secret custody/operational
approval remain gates even after functional CI and isolated-host tests pass.
