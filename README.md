# luce-pkg-server

Public implementation tracker and future Luce package/Git registry application.
MIT OR Apache-2.0. Application composition will be Luce; database, authentication,
cryptography, Git and package internals will be Luce Base. The HTTP backend will
sit behind the existing VPS HTTPS proxy.

A loopback invited-account HTTP API is implemented: `/health`,
`/v1/identity` (verified bearer identity, never proxy-header identity),
single-use `/v1/invites/redeem`, `/v1/sessions` and `/v1/sessions/revoke`.
Interactive sessions can mint and independently revoke 256-bit credentials through
`/v1/credentials` and `/v1/credentials/revoke`. Each credential is bound to one
repository, a 1-minute-to-90-day absolute lifetime, and exactly one Git or package
read/write scope. Only its SHA-256-derived storage key is persisted. Git uses the
credential as an HTTP Basic password; package APIs use it as a Bearer token.
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
Object/Git requests and responses are bounded to64MiB. The global request ceiling
is64MiB +4917 bytes to accommodate signed-release envelopes; individual handlers
retain their own limits. Incoming bodies spool above64KiB but
handlers still assemble whole objects in memory. The transport receives bodies
before handler authentication; authenticated-transfer quotas and disk-exhaustion
policy remain required before public deployment. Account JSON
handlers retain their own 4 KiB decode limits.
The store token is required in `LUCE_REGISTRY_STORE_TOKEN`; it is not an HTTP
administrator credential. There is no public bootstrap or invite-creation route.
The disposable account fixture is for tests only. Accounts use versioned password
records with native Argon2id at 64 MiB / 3 passes / 4 lanes, including integration
fixtures. Legacy unversioned accounts and test-profile sessions fail closed; there
is no automatic migration. Password hashing shares a process-wide four-slot
nonblocking admission gate; login overload returns 503 (registration already maps
service failures to 503). Valid-shaped login and invitation-redemption requests
also pass through separate allocation-free process-wide gates, each admitting 16
requests per fixed 60-second window before account lookup or password KDF. Excess
requests return 429 with `Retry-After: 60`; malformed requests do not consume a
slot. The gates are deliberately coarse and reset on process restart. Sessions
have a persisted absolute 24-hour lifetime;
expired sessions and legacy sessions without timestamps are unauthorized. The
auth library independently validates token syntax before any storage operation.
Only SHA-256-derived session identifiers are stored; raw bearer values never
appear in Prism paths or fields, and old raw-token-keyed records fail closed.
Per-account, source-address and distributed rate limits, expired-record cleanup,
credential listing/labels and account-wide emergency revocation remain pending.
Native ML-DSA-65 release signatures are implemented below.

Account signing-key enrollment uses native ML-DSA-65. Set `LUCE_REGISTRY_ORIGIN`
to the exact canonical origin clients sign (for example `https://pkg.luciaos.com`);
this is a trusted operator identifier, not a URL normalization or TLS check.
It must be at most 255 printable non-space ASCII bytes. Missing/empty configuration
disables enrollment with 503 after authentication; malformed configuration fails
startup. Neither `Host` nor forwarded headers establish this origin.
Authenticated `POST /v1/identity/key-challenge` takes an empty body and returns a
32-byte binary nonce. `POST /v1/identity/key` requires `application/octet-stream`
and exactly 5261 bytes: the 1952-byte public key followed by a 3309-byte proof using
the `luce-auth/account-possession/v1` transcript. It returns 201 `enrolled`.
Malformed requests/proofs return 400, wrong media type 415, invalid sessions 401,
enrollment/transaction conflicts 409, and operational failure 503. All responses
are no-store. Authentication is checked again inside the mutation transaction.
One replaceable challenge per account expires after five minutes. First enrollment
atomically binds the key and consumes the challenge, including across restarts;
no rotation/recovery or public key-distribution endpoint exists yet. A 409 is not proof
that a particular key was enrolled. Commit/durability failures may occur after
publication: do not assume a failed response guarantees unchanged state. Challenge
rate limiting and public deployment remain pending. These routes have a separate
5261-byte handler limit; the existing 4 KiB account JSON limits are unchanged.

Authenticated `GET /v1/identity/key` returns that session account's exact1952-byte
ML-DSA public key as no-store binary, or404 when the authenticated account is
unbound. Invalid sessions return401; read/storage/malformed-key failures return503,
never404. No account parameter or proxy-header override is accepted. Authentication
and key lookup share a snapshot in the auth library. Readback remains available
when new enrollment is disabled by missing origin configuration. This supports
reconciling uncertain enrollment responses, not public key discovery or rotation.
It binds `127.0.0.1` only. Smart Git HTTP and signed release hosting are
implemented below, but `pkg.luciaos.com` is not deployed and no real credential
has been created. A green roadmap check is not an independent authentication,
storage, cryptography or deployment review.

### Native operator and deployment tools

`src/luce_pkg_server/admin.lucb` builds the local `luce-pkg-admin` binary. Its
store secret comes only from `LUCE_REGISTRY_STORE_TOKEN` and never from argv.
`token` generates a native OS-random 256-bit hexadecimal store secret; `init`
idempotently creates the authority/repository roots in an exclusively opened
database; `invite` issues and durably publishes one single-use code through the
running owner's private Unix socket; `checkpoint` opens a stopped registry and
forces an offline durability checkpoint. There is no public invite-creation or
bootstrap endpoint.

The checked-in [deployment contract](deploy/README.md) includes a hardened systemd
unit, a bounded Caddy reverse-proxy block, and no-clobber offline backup/restore
orchestration. Backups checkpoint the native Prism database and checksum every
copied state file while excluding the store token. Restore verifies all checksums,
opens the copied database with the same native operator binary and publishes only
to a new path. Disposable tests cover wrong-token refusal, one-use invitation
redemption, repeat initialization/checkpoint, corruption rejection and restored
database reopen. These assets are preparation, not authorization to change DNS or
the running VPS.

The internal `repositories` export adds private repository creation and bounded
Git object persistence over `luce-db`/Prism. Call `initialize` on the database owner
before starting workers; each worker uses its own database connection. Every API
principal must come from verified authentication, **not** request JSON. Owners
must already have an account. Package names are lowercase ASCII letters/digits,
underscores or hyphens (1–64 bytes, first character alphanumeric); lossless hex
storage keys avoid Prism path restrictions and name aliases.

The internal `publish_release`/`get_release` storage APIs support immutable
signed releases. HTTP publication/download and `luc release-sign`,
`release-upload`, `release-check` and verified download are available; a single
convenience command named `luc publish` is not required by the wire contract.
The transport must supply an authenticated principal and configured origin.
Publication requires exact LRS1 or LRS2 `owner/package` and origin binding,
numeric toolchain version, the account's enrolled ML-DSA-65 key, a valid
signature and SHA-256 digest of the exact source pack. LRS2 additionally signs
the compiler package identity and a canonical, sorted dependency set. Its signed
commit must contain a regular root `luce.toml`; `[package]` name/language and the
complete `[registry.dependencies]` table must agree with the signed fields.
Legacy LRS1 remains accepted but does not claim source/dependency agreement.
The signed commit must already exist as a commit object in this repository. The
standalone pack must contain that commit and all typed graph dependencies
(Gitlinks remain external); duplicates, missing objects and invalid structures
are rejected. Limits are64MiB source,4096 pack objects and16M graph lookup
probes. Extra structurally valid pack objects are allowed; this does not perform
the CLI's checkout-path portability checks or require dependencies to have
already been published.

The version record atomically stores metadata, signature, historical publisher
key and source storage descriptor. Packs over1MiB use existing immutable chunk
storage. Exact metadata/signature/source retries are idempotent and complete a
durability barrier; any changed bytes at an existing version conflict, including
a newly randomized signature. Publication conflicts may require retry. Staged
chunks can remain orphaned on a later conflict/failure; quota/GC remains pending.
Commit followed by durability failure may already have published the record.
Concurrent key changes conflict with publication via a same-key-field write.
The caller's session authentication is outside this core; no session token is
accepted here. Version deletion/replacement and public-reader authorization are
not exposed. Reads currently require the repository owner and verify stored
identity, signature and source digest before returning any component as an owning
Value. This historical key is not independently trusted publisher-key distribution.

### Signed-release HTTP (scoped-credential development API)

`POST /v1/releases/{owner}/{name}` requires a live `package:publish` Bearer
credential bound to that owner and repository, an enrolled signing key, configured
`LUCE_REGISTRY_ORIGIN`, and Content-Type `application/octet-stream`. The upload
uses the following LRP1 envelope:

| Offset | Bytes | Content |
| --- | ---: | --- |
| 0 | 4 | ASCII `LRP1` |
| 4 | 2 | Little-endian metadata length M,50..24576 |
| 6 | 2 | Reserved, both zero |
| 8 | M | Canonical LRS1 or LRS2 metadata |
| 8+M | 3309 | ML-DSA-65 signature over metadata |
| 3317+M | remainder | Standalone source pack, at most64MiB |

The signed metadata selects the version; origin and qualified owner/name must
match trusted configuration and route identity. Host/forwarded headers never
override either. The handler reads bounded chunks into a bounded whole-envelope
buffer, then rechecks the live credential/principal before calling the storage core.
It does not provide early authentication before transport spooling or atomic
credential-revocation ordering throughout publication; ingress rate/quota limits and
stronger long-operation authorization remain deployment work.

Success is201 `published`, or200 `unchanged` for an exact retry. Invalid
framing/signature/digest/graph returns400, unauthenticated401, another owner403,
missing repository/commit404, version conflict or missing signing key409, wrong
media type415, and operational/unconfigured-origin failure503. Oversized requests
may be rejected by the transport before handler dispatch. A failure can follow a
successful commit; retain the exact signed upload and reconcile by download.

`GET /v1/releases/{owner}/{name}/{version}/{part}` requires a repository-bound
`package:read` or `package:publish` Bearer credential and the configured origin.
Parts are `metadata`, `signature`, `publisher_key`, `source`;
each returns verified binary bytes with Cache-Control:no-store. Invalid paths or
versions400, missing records404, and stored verification failure503. This is not
an independently trusted publisher-key directory.

`GET /v1/releases/{owner}/{name}` uses the same package-read authorization and returns the owner's available
versions in canonical descending semantic-version order as
`application/vnd.luce.versions`. The bounded LPV1 body is `LPV1`, a little-endian
u16 count, then count repetitions of one u8 byte length followed by a canonical
numeric semantic version. At most1024 versions of at most62 bytes are returned.
The server validates every storage-path encoding and every stored release identity
against the configured origin and requested owner/name before emitting the list.
An empty existing repository returns an empty catalog. The catalog is advisory:
clients must still download and verify the signed metadata, historical publisher
key, signature, source digest and Git graph. The endpoint is not anonymous and
does not change the existing owner-only Git repository visibility policy.

`tests/run_repositories.py --fixture releases` covers six modes, local/IPC/reopen,
failed-validation no-write, exact retries, immutable version conflicts, duplicate
and incomplete packs, concurrent publishers, chunked artifacts and signature
corruption. `--mode sanitize` and macOS `--mode native0 --heap` are CI gates.

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
Repository creation and owner-only raw object reads/writes are exposed over HTTP.
Those raw routes alone are **not** Git publication, but the separate Smart HTTP,
graph-validation and signed-release routes below compose the complete tested flow.
Neither route claims general SHA-1 collision-attack protection beyond the explicit
object checks documented in `luce-git`. Malformed semantic contents can be stored
but cannot be advertised as valid Git history. Storage corruption tests deliberately
modify disposable raw DB data.

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
and full Git/release workflows pass against the disposable registry; production
HTTPS acceptance remains separate.
The isolated `tests/client` consumer uses pinned `luce-http-client` and `luce-git`
to log in, create a repository, PUT/GET the actual compiler source envelope,
compare every byte and Git ID, revoke its session and verify access denial.
It runs before and after registry restart in all six compiler modes and under
ASan/UBSan. Python only starts the processes and supplies an independent HTTP
oracle; this transfer path itself is native Luce Base. The client dependency is
test-only, not a registry runtime dependency. This is not yet a `luc` command,
public HTTPS verification, Git push/pull or signed package installation.

Internal `update_refs` performs an atomic compare-and-swap batch of up to 64
`RefUpdate` records (`name`, 20-byte `expected`, 20-byte `target`). Zero expected
means creation; zero target means deletion. `get_ref` returns an owned 20-byte
Prism value or a missing error. Refs are restricted to `refs/heads/` and
`refs/tags/`, with Git syntax, a 1024-byte name bound, lossless encoded storage keys
and at most 1024 refs per repository. Branch targets must be stored commit
envelopes; tag refs may name any stored object kind. Before publishing, the same
transaction snapshot is used to traverse every target's reachable commit/tree/tag
graph, validate structural encoding and object IDs, and require matching edge
types. Missing parents, tree entries and tag targets fail the whole batch.
Gitlinks are external-repository references and are not traversed. The iterative
walk deduplicates objects across all batch roots and is bounded to 4096 objects,
65536 edges, 256 MiB of decoded envelopes and 16777216 hash-table probes. Oversized
histories are rejected, not partially checked. No commit identity/date fsck,
signature verification, ancestry/force-push policy or SHA-1 collision protection
is implied. Symbolic refs/HEAD and reflogs remain unimplemented.

Internal `receive_pack` connects the native push-command parser, complete/thin pack
decoder, immutable object storage and graph-checked ref transaction. Its principal
must already be authenticated. It validates the whole pack and the structure of
every contained tree/commit/tag before staging any objects, then publishes all refs
with compare-and-swap. Unsupported capabilities fail before staging; the accepted
set is `report-status`, `atomic`, `ofs-delta`, `delete-refs`, `object-format=sha1`
and informational `agent=` tokens. This core does not advertise capabilities,
encode report-status, expose receive-pack HTTP or implement Git authentication.
Valid staging followed by a ref conflict or disconnected graph can leave
unreferenced objects; refs remain atomic, but object storage is not rolled back.
Thin-pack bases come only from the authenticated repository's initial snapshot;
stored framing and SHA-1 are checked before reconstruction. The lookup lease and
snapshot close before staging writes. No hooks, fast-forward policy, GC or quotas
are provided.

Smart HTTP receive-pack v0 is exposed at `/git/{owner}/{name}`: authenticated
`GET info/refs?service=git-receive-pack` returns sorted snapshot refs/capabilities,
and `POST git-receive-pack` consumes the standard request media type and returns
packet-line report-status when requested. Status capacity is reserved before ref
mutation; all responses prohibit caching. The transport challenges with standard
HTTP Basic authentication. The username must equal the route owner and the
password must be a live `git:write` credential bound to that exact repository;
raw passwords, session tokens and credentials for other repositories/scopes fail
closed. Tests use stock Git's askpass/credential flow with disposable tokens passed
in process environment, never URL/config/argv. Real stock Git tests
cover initial/incremental push with large similar blobs, atomic multi-ref/tag creation, deletion,
up-to-date discovery, sorted refs, rejection reports and restart persistence.
This follows [Git's HTTP protocol](https://git-scm.com/docs/gitprotocol-http).
Smart HTTP upload-pack v0 is also exposed through `GET/HEAD info/refs?service=git-upload-pack`
and `POST git-upload-pack`, with `git:read` or `git:write` Basic credentials and
no-store responses. Discovery peels annotated tags, including nested tags, and emits HEAD
plus `symref=HEAD:refs/heads/main` when `main` exists. The current default-branch
policy is fixed to `main`, not a configurable persisted symbolic-ref API; missing
`main` means no advertised HEAD. Git protocol v2 is not negotiated. Clone/fetch
tests use stock Git, compare file contents, and run strict fsck; no runtime Git
subprocess is used. Pack count, byte, lookup and depth limits still apply. HTTP
fetch requests are capped at 1 MiB and responses at 64 MiB; response assembly is
buffered, not streaming. No live deployment or real credentials are involved.

Internal `upload_pack` now implements bounded stateless fetch selection from one
authenticated snapshot. Wants must equal current ref tips or advertised peeled tag
targets; unadvertised object IDs
are rejected. It validates the wanted closure, acknowledges only commits in that
closure, and subtracts the validated common-history closure before generating a
full-object pack. A negotiation round returns ACK/NAK without a pack until `done`.
Unknown/unrelated haves are ignored, not used as an arbitrary-object probe. It is
read-only, retains object leases only through pack encoding, and inherits graph
and pack resource limits. Discard output on any failure. Supported capability
tokens are `ofs-delta`, `no-progress`, `object-format=sha1`, and informational
`agent=`; multi-ACK, side-band, shallow and filter extensions are not implemented.
Tag peeling validates object IDs and target kinds, is limited to 64 tag levels,
and shares a 64 MiB object-byte budget per discovery/authorization operation.

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
commits now contain valid empty trees. The separate `graph` fixture checks real
blob/tree/commit/tag relationships, missing and mistyped edges, malformed commits,
submodule exclusions, the traversal object bound and atomic rejection, locally and
over IPC with fresh-process reopen. These are not yet full Git push/pull tests.
The harness reports per-command elapsed time. The full 64 MiB large-object
boundary has a 600-second ceiling (other commands retain 180 seconds): the
unoptimized-C fixture exceeded 180 seconds on hosted Linux. This is a correctness
allowance, not a performance claim; the exact boundary/data assertions remain.

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
The revised [package/application plan](docs/PACKAGE_APPLICATION_PLAN.md) gives the
authoritative implementation order from `package.prisma` and sandboxed
`install.luc` through staging and activation of `pkg.luciaos.com`.
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
migrate project manifests. The `package.prisma`/Prism-lock implementation and real
registry gates remain open.
