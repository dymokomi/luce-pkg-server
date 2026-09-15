# luce-pkg-server

Public implementation tracker and future Luce package/Git registry application.
MIT OR Apache-2.0. Application composition will be Luce; database, authentication,
cryptography, Git and package internals will be Luce Base. The HTTP backend will
sit behind the existing VPS HTTPS proxy.

**No registry server is implemented or deployed by this repository yet.** A green
roadmap check is not an authentication, storage, cryptography or deployment gate.

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
The owner selected a separate `luc` product, planned in `luce-cli`, instead of
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
