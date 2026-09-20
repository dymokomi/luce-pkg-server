# Package, application and registry execution plan

Revised 2026-09-20. This is the authoritative implementation order for the
package/application workflow ending in activation of `pkg.luciaos.com`. It
supersedes the earlier user-facing `luce.toml` and TOML-lock target. Existing
implementations and compiler fixtures remain compatibility inputs until their
replacement gates pass.

## Fixed product contracts

- `luc` is shipped by the public `luce-luc` repository and is the one project,
  toolchain, package and application command.
- `package.prisma` is the one authored package definition. It contains identity,
  requirements, named outcomes, targets, resources, recipe declarations and
  requested permissions.
- `install.luc` is optional high-level Luce source referenced by
  `package.prisma`. Recipe source is not embedded in the Prism document.
- `luc.lock` remains separate generated state, encoded as canonical Prism text.
- Current compilers may continue to consume `luce.toml`; `luc` generates that
  adapter in its private build directory. New projects do not need to author it.
- A package can expose several named outcomes: libraries, executables,
  applications, plugins and resource trees. Requirements select outcomes, and
  Prism connections express dependencies between outcomes.
- `luce run --sandbox ROOT FILE -- ARGS` is the public recipe-execution boundary.
  This changes Luce tooling, not Luce language syntax.
- Sandboxed source is interpreted as high-level Luce. Direct or transitive Luce
  Base imports, native compilation, FFI and native packages are refused.
- Recipes are deterministic plan generators. They do not directly modify the
  filesystem, launch programs, access the network or discover dependencies.
- `luc` validates a returned Prism plan, stages its operations, commits them
  atomically and records a receipt. Uninstall never runs package code.
- Package and release signatures remain ML-DSA-65. Local credential vaults remain
  Argon2id plus XChaCha20-Poly1305.
- Developers use ordinary Git clients over standard HTTP(S). The server's Git
  object/protocol implementation remains native Luce Base; stock Git is an
  interoperability client, not the production server engine.
- The application binds loopback HTTP on the VPS. The existing reverse proxy
  terminates public HTTPS only after staging and operational gates pass.

## Ordered execution

### 0. Rebaseline and freeze the revised contracts

Repositories: all pinned dependencies, `luce-pkg-server`.

1. Record exact current commits for Luce, Luce Base, Luc, Prism, crypto, TLS,
   database, auth, Git, HTTP and server packages.
2. Run their existing local gates and confirm public CI at those commits.
3. Version the `package.prisma`, `luc.lock`, install-plan and sandbox-policy
   schemas. Define canonicalization, size/depth/count bounds and diagnostics.
4. Preserve a read-only `luce.toml` migration path; do not maintain two writable
   dependency models.

Gate: one reviewed contract suite rejects ambiguous encodings, unknown required
fields, duplicate identities, graph cycles, path escapes and downgrade attempts.

### 1. Make Prism the package substrate

Repositories: `luce-prism`, `luce-pkg`.

1. Define the `luc.package/1` schema for identity, requirements, outcomes,
   resources, targets, recipes and permissions.
2. Define `luc.lock/1`, `luc.install-context/1`, `luc.install-plan/1` and
   `luc.install-receipt/1` schemas.
3. Add canonical semantic encoding and hashing independent of whitespace.
4. Define safe external-file references. Recipe paths are relative to the
   manifest, may not be absolute, may not contain escaping `..`, and may not
   resolve through a symlink outside the package root.
5. Bind every referenced file's digest into release metadata and the lock.

Gate: text/binary round trips, canonical hash fixtures, schema fuzzing, hostile
paths and cross-platform path cases pass in all supported compiler modes.

### 2. Add the Luce sandbox execution boundary

Repository: `luce` with platform support from Luce Base APIs.

1. Add `luce run --sandbox ROOT FILE -- ARGS` while retaining ordinary
   `luce run FILE` compatibility.
2. Use a parent/child design so the child enters OS confinement before it reads,
   lexes or parses untrusted source.
3. Root module discovery inside `ROOT`; reject escaping symlinks, ancestor
   manifests, external path dependencies and all direct/transitive Base imports.
4. Execute only through the existing Luce interpreter. Do not emit or execute
   native recipe code.
5. Apply wall-time, CPU, memory, thread/process, descriptor, log and result-size
   limits. Network and child-process creation are denied.
6. Implement Linux with Landlock, seccomp and `no_new_privs`; Windows with
   AppContainer/LPAC and a Job Object; and macOS with a separately signed sandbox
   helper. A missing or failed backend is a hard error for remote recipes.
7. Version the sandbox policy and include the policy/toolchain identity in locks
   and release verification.

Gate: adversarial tests prove Base-import refusal, root and symlink containment,
network/process denial, timeout and memory termination, bounded output, process
cleanup and no writes outside the private sandbox area. Each platform is claimed
only after its native escape suite passes.

### 3. Implement package and lock semantics

Repository: `luce-pkg`.

1. Parse and validate `package.prisma` without executing recipes.
2. Resolve version constraints and named outcomes deterministically.
3. Detect dependency and outcome cycles and incompatible targets/toolchains.
4. Write canonical `luc.lock` with exact origin, package, version, Git commit,
   source digest, referenced-file digests, toolchain, sandbox policy and complete
   transitive outcome graph.
5. Preserve verified content-addressed downloads and offline/relocated caches.
6. Provide a one-way importer from legacy `luce.toml`; never silently rewrite a
   project during build or resolution.

Gate: resolver property tests, conflicting graphs, lock stability, tamper and
rollback rejection, offline replay and cache relocation pass.

### 4. Make local Luc workflows use the new model

Repository: `luce-luc`.

1. Update `luc init`, `add`, `remove`, `lock`, `sync`, `build`, `run`, `test` and
   project inspection to use `package.prisma` and `luc.lock`.
2. Generate private transient `luce.toml` adapters for current `luce` and
   `luce-base` compiler invocations.
3. Pin the exact Luce/Luce Base/standard-library toolchain; never select an
   arbitrary executable from `PATH` when a lock requires another identity.
4. Preserve argument bytes and invoke tools without a shell.
5. Keep legacy projects readable and provide an explicit migration command.

Gate: fresh Luce and Luce Base library projects import, link, build, test and run
online, locked, offline and with a relocated cache without modifying user source.

### 5. Implement applications and sandboxed recipes

Repositories: `luce-luc`, `luce-pkg`, `luce`.

1. Add `luc install`, `uninstall`, `upgrade`, `list` and ephemeral `luc x`.
2. Build an isolated recipe root containing the referenced `install.luc`, a
   generated wrapper/context and the pure high-level `luc.install` SDK.
3. Invoke it only with `luce run --sandbox` and accept a bounded canonical Prism
   plan.
4. Support a small operation set: compile declared inputs, copy declared files or
   trees, install executables/resources, create launchers/application bundles and
   emit bounded generated text. There is no arbitrary shell operation.
5. Use logical destination handles rather than absolute paths. Validate every
   operation against the manifest and policy.
6. Stage, verify and atomically publish installations. Record file hashes and
   ownership in a receipt; rollback on every interruption or failure.

Gate: malicious-plan, traversal, collision, concurrent-install, interruption,
rollback and exact-uninstall tests pass. No recipe can mutate the final prefix.

### 6. Convert `luced` into the reference application

Repositories: `luced` and its package dependencies.

1. Add `package.prisma` and, only where declarative outcomes are insufficient,
   `install.luc`.
2. Replace sibling paths with registered requirements and named library outcomes.
3. Declare the editor executable and grammar/resource trees as outcomes.
4. Test per-user installation, launch, grammar discovery, upgrade and uninstall
   on supported macOS and Linux targets.
5. Use `luced` as the end-to-end hostile-path, receipt and reproducibility fixture.

Gate: a clean machine can build and install `luced` from only its lock and verified
cache, and uninstall removes exactly receipt-owned files.

### 7. Close the infrastructure library gates

Repositories: `luce-compress`, `luce-crypto`, `luce-prism`, `luce-db`,
`luce-auth`, `luce-git`, `luce-server`, `luce-http-client`, `luce-tls`.

1. Finish the remaining bounded-resource, fault-injection, recovery and
   interoperability tests already listed in the public tracker.
2. Complete TLS 1.3, X.509 path/hostname verification, DNS and verified HTTPS in
   the native client before any real credential is transmitted.
3. Complete account/device/recovery/token storage and key rotation.
4. Complete Git pack/ref/Smart HTTP behavior and collision defenses.
5. Obtain independent crypto, storage and protocol review; resolve findings.

Gate: current Linux/macOS CI, sanitizers, isolated VPS tests and independent review
all pass with no real production credentials involved.

### 8. Complete invited accounts and operator workflows

Repositories: `luce-auth`, `luce-luc`, `luce-pkg-server`.

1. Implement operator invite creation/revocation and user/device enrollment.
2. Implement `luc auth register`, login, logout, device addition/revocation and
   scoped credential storage in the encrypted local vault.
3. Enforce one-use, expiry, concurrency and replay behavior server-side.
4. Redact invitations, tokens, passwords, seeds and authorization headers from
   errors, logs and CI artifacts.

Gate: disposable identities pass concurrent registration, expiry, revocation,
recovery and lost-device tests over verified staging HTTPS.

### 9. Complete Git hosting

Repositories: `luce-git`, `luce-pkg-server`, `luce-luc`.

1. Serve standard Smart HTTP discovery, fetch and receive-pack from Prism-backed
   storage with repository ACLs and atomic ref updates.
2. Support stock `git clone`, `fetch` and `push`; Luc may configure remotes and
   mint scoped credentials but does not replace normal local Git commands.
3. Bound pack/object/ref counts, decompression, memory, CPU and concurrent pushes.
4. Reconcile interrupted and ambiguous pushes without exposing partial refs.

Gate: stock Git interoperability, concurrent/aborted push, authorization isolation,
large-object bounds and backup/restore tests pass.

### 10. Publish signed package/application releases

Repositories: `luce-pkg`, `luce-pkg-server`, `luce-luc`.

1. Extend signed release metadata to bind `package.prisma`, every referenced file
   including `install.luc`, the source commit, outcome graph, permissions, targets,
   compiler/toolchain and optional artifact digests.
2. Have the registry parse and index static Prism metadata but never execute a
   recipe.
3. Authorize immutable release creation only from an owned repository and an
   existing commit whose package document matches the signed metadata.
4. Add root metadata expiry, rotation and rollback protection without algorithm
   downgrade.
5. Implement remote `luc publish`, `add`, `lock`, `sync`, `install` and `x` over
   verified HTTPS.

Gate: tamper, replay, rollback, mismatched-reference, unauthorized-publisher and
DB/object-consistency tests pass; source and optional artifacts reproduce from the
same locked identities.

### 11. Run an isolated end-to-end staging deployment

Repositories: `luce-pkg-server` plus deployment assets.

1. Build a reproducible Linux release bundle from pinned public commits and verify
   every checksum before copying it to the VPS.
2. Back up and restore the Prism state in an isolated location.
3. Bind the staging service to a new loopback port. Do not alter existing sites.
4. Add a temporary restricted reverse-proxy route only after reviewing its diff.
5. Use disposable accounts, keys, invitations, repositories and package names.
6. Exercise registration, stock Git push/clone, release publication, download,
   sandboxed installation and both-language consumer builds.
7. Restart, upgrade, roll back and restore while checking all existing services.

Gate: the complete staging matrix passes repeatedly and cleanup leaves existing
applications, proxy routes and production data unchanged.

### 12. Operational readiness and production activation

Repositories: `luce-pkg-server` and private operator records for secrets only.

1. Approve production key custody, invitation custody, backup encryption,
   rotation, revocation and recovery procedures.
2. Set quotas, admission limits, monitoring, alerts, log retention and redaction.
3. Verify service hardening, non-root ownership, loopback binding, restart policy,
   filesystem permissions and restore drills.
4. Build and archive the exact production bundle and rollback bundle.
5. Take a fresh backup, install the immutable release, add the reviewed Caddy site
   for `pkg.luciaos.com`, reload, and verify public HTTPS and backend isolation.
6. Roll back immediately if any health, TLS, auth, Git or package check fails.

Gate: public health and negative-security probes pass, existing hosted sites remain
healthy, and a restore/rollback remains immediately available.

### 13. Final real-user acceptance

1. Generate a production invitation through the approved operator procedure.
2. Register `dymokomi` with an ML-DSA-65 account/device key.
3. Create a public remote package repository.
4. Add the `pkg.luciaos.com` Git remote and push with stock Git.
5. Publish a signed release with Luc.
6. On a clean environment, use Luc to download it, import it into fresh Luce and
   Luce Base projects, build and run both.
7. Install `luced`, verify its resources and launch, uninstall it, then repeat from
   the lock with network disabled and a relocated cache.
8. Record only public commits, release identities and redacted test evidence. Never
   commit invitations, passwords, tokens, vaults or private keys.

The production goal is complete only after all eight final steps pass against the
public origin. Deployment alone is not completion.
