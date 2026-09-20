# Execution order and acceptance gates

Started 2026-09-14. The owner requested sequential, tested milestones with public
repositories and commits. Runtime packages use MIT OR Apache-2.0 and native Luce
Base internals; existing OS facilities and the deployed HTTPS proxy are explicit
platform boundaries. Foreign programs may generate independent test fixtures, but
are not hidden production implementations. External Git and SQLite remain unselected.

| ID | Work | Required evidence before completion |
| --- | --- | --- |
| M0 | Contracts, threat model, schemas and compatibility | Versioned decisions for origin/proxy, storage, identities/invitations, Git, release trust, manifests/locks, targets and operations |
| M1a | `luce-compress` | Bounded streaming DEFLATE/zlib; independent fixtures in both directions; incremental/consumed-byte, truncation, bomb, overflow and ownership tests |
| M1b | `luce-crypto` | Official vectors, independent differential/negative tests, entropy failure and secret ownership; generated-code/constant-time review |
| M1c | `luce-db` | Atomic races, snapshots, bounded writer lifecycle, deterministic I/O/crash recovery, checkpoint/migration/restore and resource tests |
| M1d | `luce-prism` package substrate | Canonical package/lock/context/plan/receipt schemas, external-file digests, bounds, hostile paths and semantic hash fixtures |
| M2a | `luce-git`, offline | Objects/packs/refs, graph and collision validation, ref races and stock-Git interoperability |
| M2b | `luce-auth`, offline | One-use invitations, keys/devices, local vault, recovery/revocation and no plaintext secrets in storage/history |
| M2c | `luce-pkg`, offline | `package.prisma`, Prism `luc.lock`, named outcomes, deterministic resolution, canonical verified archives/cache and hostile-input tests |
| M2d | Luce sandbox | `luce run --sandbox ROOT`: interpreted high-level Luce, rooted imports, Base/native refusal, OS confinement and resource/escape tests |
| M3a | HTTP/proxy foundation | Early admission, streaming/limits/cancellation, binary traffic, trusted-header rules and non-public backend binding |
| M3b | `luce-tls` / `luce-http-client` | Native verified HTTPS; certificate/hostname/trust/redirect failures; review before real credentials |
| M4 | Invited account API / operator CLI | Registration proof + one-use invite, concurrent duplicate/expired/revoked claims, scoped tokens and redacted logs |
| M5 | Git hosting | Standard HTTPS clone/fetch/push, ACL/ref/object isolation, aborted/concurrent pushes and bounded resource use |
| M5b | Pull requests without forks | Same-repository branch reviews, durable state, concurrent numbering, bounded ancestry-verified merge state and stock-Git/HTTP tests; collaborator ACLs remain separate |
| M6 | Signed package releases | Authorized release-from-commit, immutable versions, tamper/replay/rollback rejection and DB/object consistency |
| M7 | Local `luc` libraries and applications | Compiler adapters, sandboxed `install.luc`, staged installs/receipts, fresh import/link/build and `luced` application acceptance |
| M8 | Remote `luc` integration | Verified publish/add/lock/sync/install/x against signed releases with both toolchains and offline/relocated replay |
| M9 | Isolated staging | Disposable invited users, stock Git, package publication/download, application install, restart/upgrade/rollback/restore on the VPS without production activation |
| M10 | Operational readiness and production | Independent reviews, key custody/rotation, quotas/monitoring, backup/restore, immutable deployment, reviewed proxy activation and rollback |

Follow the prerequisites in `roadmap.json`, not repository creation order. Never
label a dependent milestone complete with an incomplete prerequisite. Existing DB
sub-slices are useful evidence, not an exemption from M0 or the remaining M1c gates.
Progress status is `pending`, `in_progress` or `complete`; unfinished work is not
silently converted into success because a time/token budget was used up.

## Contract checkpoint

Decided by the owner:

- Independent public repositories and dual licensing; native Base internals.
- Native `luce-db`, with a multithreaded service based on `luce-server`.
- Ordinary HTTP backend behind existing HTTPS termination; no custom Git transport
  helper or strict post-quantum transport requirement for this first deployment.
- Invitation-gated accounts. Final owner handle `dymokomi`; secrets are not public.
- Standalone `luc` from `luce-luc` manages toolchains, projects, packages and
  applications for both languages. This replaces the earlier embedded compiler-CLI
  requirement; see [CLI_DECISION.md](CLI_DECISION.md). Real compile/link acceptance remains.
- Application signatures are ML-DSA-65; local vaults are Argon2id +
  XChaCha20-Poly1305. See [APPLICATION_CRYPTO_PROPOSAL.md](APPLICATION_CRYPTO_PROPOSAL.md).
- The authored package document is `package.prisma`; optional high-level Luce
  installation logic lives in a referenced `install.luc`. `luc.lock` remains a
  separate generated file but contains canonical Prism text. Current compilers
  continue to receive private generated `luce.toml` adapters. See
  [CONTRACTS.md](CONTRACTS.md) and the authoritative
  [package/application plan](PACKAGE_APPLICATION_PLAN.md).

Current implementation constraints:

- Pin supported toolchains; initially validate macOS arm64 and Linux x86-64 in all
  four native optimization modes and both C comparison modes. No Windows claim
  without a Windows gate. Luce language syntax remains unchanged, but the Luce
  tool must add the versioned `run --sandbox` boundary. Test versioned compiler
  adapters in `luc`.
- Native worker state may cross threads only under its ownership contract; Luce
  managed references stay worker-local. No unbounded per-request threads.
- Public clients require verified HTTPS. The external proxy does not provide the
  remote client's TLS implementation. No insecure fallback or foreign TLS shortcut.
- No production secrets or public auth listener before security/operational gates.
- Stock Git is an interoperability client/oracle, not a selected server subprocess.
- `luce-db` WAL remains experimental. Explicit checkpoint/compaction, backup
  restore, application schema migrations and process-RSS measurements exist as
  tested sub-slices.

Still to design/review, so M0 is not complete:

- Versioned identity/proof/signature/key-role, vault/recovery and challenge/token
  encodings beyond the LID1 invite/vault wrap; registry-root signature and
  freshness/rotation policy. ML-DSA-65 LRS1/LRS2 release signatures and LRS2
  source-manifest agreement are implemented; remaining record kinds and root
  trust metadata are not all implemented.
- Canonical Prism `package.prisma` and `luc.lock` schemas, named outcomes,
  install context/plan/receipt schemas, recipe-file digest binding and migration
  from the implemented TOML slice. Hostile-input and archive/cache work remain.
- Git packs/refs/Smart HTTP, SHAttered-prefix rejection in the object store, and
  advertised capability/resource limits. Blob SHA-1 object IDs exist.
- Exact proxy/backend trust, headers, framing, certificate policy and deployment
  limits. Loopback invited-account HTTP now exists; public `pkg.luciaos.com` does
  not. The existing proxy is Caddy; identifying it is not deployment approval.
- Native TLS handshake, X.509 path building and verified HTTPS. HKDF-Expand-Label,
  record headers and DNS-ID matching exist in `luce-tls`; the HTTP client is
  still cleartext.
- Native storage checkpoint/replacement/migration/recovery contract, memory budgets,
  durability limits and safe shutdown. SQL/replication remain later work.
- Locate the earlier TLS checkpoint before duplicating it; arrange independent
  crypto/storage/protocol review before production use of real credentials.

The [application crypto profile](APPLICATION_CRYPTO_PROPOSAL.md) records the accepted
ML-DSA-65 and Argon2id + XChaCha20-Poly1305 choices. Encodings, costs and review
remain open. Isolated-host evidence in this tracker omits host/service identifiers;
those stay in the private operator workspace notes.

Small primitives with settled format/ownership contracts may be implemented and
tested while unrelated M0 decisions remain open. Such work is recorded as a
sub-slice, not a completed dependent milestone. First new package: compression,
whose wire format is independently standardized and does not select account keys.

## Completion evidence

Each milestone needs reviewed source commit(s), relevant positive and negative
tests, supported-host CI links, and explicit remaining exclusions. Data in the
tracker is an evidence index, not a cryptographic attestation or an automated
security review. CI validates tracker structure, not the truth of external claims.
Secrets, host access material, account/private keys, invitations and bearer tokens
must never enter this repository or CI logs.

Final acceptance is separately tracked. Use disposable identities during staging;
create the owner's real account only through the approved custody/registration
procedure. Publish only authorized package snapshots, never arbitrary dirty trees
or all workspace contents. Preserve GitHub mirrors as recovery/bootstrap inputs.
