# luce-pkg-server

Public implementation tracker and future Luce package/Git registry application.
MIT OR Apache-2.0. Application composition will be Luce; database, authentication,
cryptography, Git and package internals will be Luce Base. The HTTP backend will
sit behind the existing VPS HTTPS proxy.

A loopback invited-account HTTP API is under integration: `/health`,
`/v1/identity` (verified bearer identity, never proxy-header identity),
single-use `/v1/invites/redeem`, `/v1/sessions` and `/v1/sessions/revoke`.
Authenticated `POST /v1/repositories` accepts exactly `{"name":"package-name"}`
and creates a private repository owned by the verified session user. It returns
201 on creation, 409 on duplicate/concurrent conflict, 400 for invalid fields,
401 for missing/invalid/revoked sessions and 503 for storage failures. It accepts
no owner override; reverse-proxy identity headers grant no authority. A conflict
may require reconciliation/retry, not necessarily mean the requested name exists.
Two application workers use one Prism database owner through local IPC.
Authenticated `PUT`/`GET /v1/repositories/{owner}/{name}/objects/{id}` transfer
canonical **uncompressed** Git object envelopes (not Git smart HTTP or zlib loose
files). Only the verified owner may access a repository; other principals get 403.
PUT validates the requested 40-hex SHA-1 against the exact envelope before writes,
returns 200 with that ID after durable storage (also for exact retries), 400 for
invalid input, 404 for missing repositories, 409 for conflicts and 503 for storage
failure. GET returns binary bytes with 200, missing objects with 404, and storage
or integrity failure with 503. Handler responses use `Cache-Control: no-store`.
Requests/responses are bounded to 64 MiB; incoming bodies spool above 64 KiB but
handlers still assemble whole objects in memory. The transport receives bodies
before handler authentication; per-account quotas, early admission/rate limits
and disk-exhaustion policy remain required before public deployment. Account JSON
handlers retain their own 4 KiB decode limits.
The store token is required in `LUCE_REGISTRY_STORE_TOKEN`; it is not an HTTP
administrator credential. There is no public bootstrap or invite-creation route.
The disposable account fixture is for tests only. Password costs remain test-only;
rate limits, expiry, account signatures and production credential policy are pending.
It binds `127.0.0.1` only. This is not `pkg.luciaos.com`, Git hosting, signed
releases or real credentials. A green roadmap check is not an authentication,
storage, cryptography or deployment gate.

The internal `repositories` export adds private repository creation and bounded
Git object persistence over `luce-db`/Prism. Call `initialize` on the database owner
before starting workers; each worker uses its own database connection. Every API
principal must come from verified authentication, **not** request JSON. Owners
must already have an account. Package names are lowercase ASCII letters/digits,
underscores or hyphens (1–64 bytes, first character alphanumeric); lossless hex
storage keys avoid Prism path restrictions and name aliases.

Objects are canonical uncompressed Git envelopes, limited to 64 MiB each. Exact
duplicates are idempotent, differing bytes at the same ID conflict, and reads
recheck framing and Git identity. Successful writes include the database bake
barrier; an error can still mean a commit happened before its barrier failed.
Callers must reconcile ambiguous outcomes, not assume rollback. Returned Prism
values are owned and must be released. Objects up to 1 MiB retain the original
inline format. Larger objects use immutable 1 MiB chunks under a SHA-256 content
key; each chunk is a bounded transaction/IPC value. After staging and a bake
barrier, one small manifest transaction publishes the object. Incomplete staging
is invisible to object reads and is resumable after restart. Reconstruction
checks manifest bounds, exact chunk lengths, SHA-256 content and Git identity.
Reads still assemble the entire object in bounded memory; this is not a streaming
API. Interrupted/conflicting uploads can leave orphan chunks, and quotas, garbage
collection and disk-exhaustion policy are not implemented. The content checksum
is not publisher authentication or comprehensive SHA-1 collision-attack detection.
Repository creation and owner-only object reads/writes are exposed over HTTP.
This is **not** SHA-1 collision-attack protection, commit/tree semantic validation,
graph reachability, Git push/pull, publisher authorization or signed releases.
Malformed semantic contents can be stored and must not be advertised as a valid
Git history. Storage corruption tests deliberately modify disposable raw DB data.

```sh
python3 tools/bootstrap_registry.py
python3 tests/run_repositories.py
python3 tests/run_repositories.py --mode sanitize
python3 tests/run_repositories.py --fixture large_objects
python3 tests/run_repositories.py --fixture large_objects --mode sanitize
```

These tests cover fresh-process reopen, local/IPC reads and writes, concurrent
duplicate creation through worker-local clients, ownership rejection, exact 1 MiB
binary objects, name/path boundaries, idempotence and persisted-content tampering.
Large-object tests use an actual tracked Luce Base bootstrap source, a 17 MiB
object exceeding Prism's 16 MiB IPC frame limit, and the full 64 MiB object bound.
They also exercise inline/chunk split boundaries, independent-process reopen,
interrupted staging/restart/resume and corrupted chunks/manifests. HTTP integration
uploads/downloads real bootstrap source, checks chunked requests, rejection without
writes, cross-account denial, revocation and restart. Native luc remote integration
and full Git/release workflows are still required for real package acceptance.

Internal `update_refs` performs an atomic compare-and-swap batch of up to 64
`RefUpdate` records (`name`, 20-byte `expected`, 20-byte `target`). Zero expected
means creation; zero target means deletion. `get_ref` returns an owned 20-byte
Prism value or a missing error. Refs are restricted to `refs/heads/` and
`refs/tags/`, with Git syntax, a 1024-byte name bound, lossless encoded storage keys
and at most 1024 refs per repository. Branch targets must be stored commit
envelopes; tag refs may name any stored object kind. This checks envelope identity
and kind, **not** commit structure, graph completeness, ancestry or force-push
policy. Symbolic refs/HEAD, reflogs and HTTP ref endpoints are not implemented.

Every expected ID and the final namespace is checked before one transaction is
committed. Prefix conflicts (`topic` versus `topic/child`) are rejected, including
concurrent creation. A shared per-repository marker write forces competing batches
to conflict even when they touch different ref names, because Prism does not track
read predicates. Ref renames expressed as delete+create are permitted when the
final namespace is valid. Errors before commit publish no partial batch; errors
after commit can have ambiguous durability outcomes, as with object writes.

```sh
python3 tests/run_repositories.py --fixture refs
python3 tests/run_repositories.py --fixture refs --mode sanitize
python3 tests/run_repositories.py --fixture refs --mode native0 --heap # macOS
```

Ref fixtures cover stale IDs, malformed/bounded inputs, owner rejection, absent
objects and wrong branch target kinds, atomic multi-ref failure and renames,
prefix/batch worker races, the full 1024-ref bound and restart persistence. Fixture
commit payloads are deliberately opaque: these are ref-storage tests, not Git
history acceptance tests.

macOS heap tests capture output in regular files and wait for the leak tool's
actual exit status, then clean up only the process group launched by the test.
This avoids waiting forever on output handles retained by a stopped instrumented
child after the tool completes. Fixture completion, ordinary child status and
zero-leak assertions remain required; true tool timeouts still fail. The helper
and lifecycle regressions are adapted from this author's dual-licensed
`luce-auth` test harness, not linked into registry runtime code.

## End-to-end goal

1. Register the owner's `dymokomi` account at `https://pkg.luciaos.com` through
   invitation-gated registration, with private credentials kept off GitHub/logs.
2. Upload Git history and publish immutable, verified source-package releases.
3. Download those releases with the standalone `luc` client over verified HTTPS.
4. Use `luc` to create/manage projects targeting `luce` and `luce-base`; import, link,
   build and run consumers, then repeat locked/offline and after cache relocation.
5. Exercise invalid invitations, authorization failures, tampered downloads,
   conflicting versions, interrupted operations, revocation and service restore.

Repository creation, local demos and test accounts alone do not satisfy this goal.
The owner selected the existing separate `luc` product in `luce-luc`, instead of
requiring embedded compiler package commands. Language sources remain untouched;
toolchain compatibility and real import/link/build tests remain required. See the
[client decision](docs/CLI_DECISION.md). Deployment configuration and real key custody are reviewed
before activation; current VPS testing is isolated and uses disposable test data.

## Work order

[ROADMAP.md](docs/ROADMAP.md) explains the dependency order and open contracts.
[roadmap.json](roadmap.json) records status and evidence. Each library lives in its
own public repository; commits should contain focused implementation and regression
tests. Sub-slices may be tested before their parent milestone is complete.

The native [luce-db](https://github.com/dymokomi/luce-db) prototype is already public
and tested on Linux/macOS and an isolated VPS. It is still experimental: its
remaining persistence gates are not complete.

```sh
python3 tests/check_roadmap.py
```

This command checks the tracker, dependency ordering and completion evidence rules,
including negative tests. It does not execute future product acceptance tests.

An additional [compiler compatibility profile](docs/COMPILER_PROFILE.md) checks
real Base/Luce imports, transitive native inputs, package/type/error identity,
argument forwarding and source relocation in all six compiler modes. It provides
an executable M0 boundary for future `luc` adapters; it is not an installer or a
completed package journey. It uses only copied synthetic fixtures, without editing
the language repositories or user projects.

```sh
python3 tools/bootstrap_compilers.py
python3 tests/test_compiler_protocols.py
python3 tests/check_compilers.py
```

To reuse trusted pinned compiler builds, pass `--base PATH --luce PATH` to the last
command. Current TOML inputs are compatibility fixtures, not a decision to silently
migrate project manifests. The manifest/lock and real registry gates remain open.
