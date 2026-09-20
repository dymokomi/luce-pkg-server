# Standalone `luc` client decision

Owner decision: 2026-09-14 PDT / 2026-09-15 UTC. This supersedes the earlier plan
to require package commands inside the `luce` and `luce-base` compiler executables.
The other team continues compiler bug fixes and standard-library linking work;
this project does not change Luce language syntax or assume that work is frozen in
time. It does add the sandboxed-run tooling boundary to the Luce repository. Pin
and test the compiler revisions used by each supported client release.

The independent public repository is **`luce-luc`**, shipping **`luc`**.
It manages projects, toolchains and packages for both Luce and Luce Base. Command
composition may be Luce; implementation libraries remain Luce Base. This decision
does not authorize foreign dependency solvers, package engines or TLS/crypto.

The owner's UX reference is [uv's project and version management](https://docs.astral.sh/uv/):
one front door for initialization, dependencies, locking/synchronization, execution
and toolchain selection. It is a UX reference, not a requirement to reproduce every
Python-specific feature or to use uv as an implementation dependency.

## Responsibilities and compatibility

- `luc`: command UX, project initialization, toolchain discovery/pinning, build/run
  orchestration, registry/account/repository operations and diagnostics.
- `luce-pkg`: the shared native manifest/lock/resolution, verification, cache and
  installation implementation. Do not embed a second solver in command handlers.
- `luce` / `luce-base`: compiler executables invoked with explicit arguments and
  pinned compatibility profiles. Existing direct compiler use keeps working.
- Registry/auth/network libraries retain their existing trust and review gates.
  Compiler invocation is an intentional process boundary, not a shell command
  interpolation boundary. Propagate failures and cancellation; preserve arguments
  containing spaces/metacharacters without executing them as shell syntax.

The authored project input is now `package.prisma`, with generated canonical Prism
state in `luc.lock`. Current compiler-compatible `luce.toml` is an internal adapter
format and a read-only legacy migration input. `luc` must not silently rewrite an
existing project or maintain divergent solvers. It may generate a private transient
compiler manifest under its build directory.

The Luce language syntax remains unchanged. The Luce tool gains
`luce run --sandbox ROOT FILE -- ARGS` so `luc` can execute a referenced high-level
`install.luc` recipe as an interpreted, rooted, OS-confined plan generator. This is
a versioned toolchain interface and is pinned with the compiler/runtime identity.

Toolchain selection must bind compatible `luce`, `luce-base`, standard-library and
target/linking identities, not just whichever executable happens to be on `PATH`.
Start with explicit installed/pinned toolchains; remote installation additionally
requires verified distribution metadata/downloads, quarantine and recovery. Never
overwrite a developer's unrelated installation or auto-download during compilation.

## Proposed commands, not implemented commands

```sh
luc init demo --language luce
luc init native-demo --language luce-base
luc toolchain list
luc toolchain pin TOOLCHAIN_ID
luc add 'dymokomi/luce-image@^1.2'
luc lock
luc sync --locked
luc build --locked
luc run --locked
luc sync --locked --offline
luc checkout dymokomi/luce-image --revision COMMIT_ID --destination ./image-source
luc auth register --server https://pkg.luciaos.com --user dymokomi
luc repo create dymokomi/luce-image --visibility public
luc package publish dymokomi/luce-image --version 1.2.0 --commit COMMIT_ID
```

Exact flags, manifest/lock encodings and editable checkout behavior are still
versioned API work. Registration prompts for invitation/private credentials through
protected channels. Ordinary developers may continue using stock `git commit` and
`git push` against standard HTTPS remotes; `luc` does not replace those workflows.

## Changed acceptance gate

M7 and M8 now prove the real standalone `luc` journey against both compiler executables:
create fresh projects, select/pin compatible toolchains, resolve and install verified
sources, import/link/build/run, then repeat with locked/offline/relocated caches.
Also test incompatible toolchains, missing verified artifacts, argument fidelity,
conflicting graphs, sandbox escape attempts, interrupted application installs,
receipts/rollback and project/user-file preservation.

No `luce pkg` or `luce-base pkg` implementation is required for this acceptance.
Optional compiler aliases could delegate to `luc` later, under separate approval;
they are not required to finish this plan. Local M7 depends on the package and
sandbox milestones; remote M8 additionally depends on verified HTTPS and signed
releases. Actual import/link correctness remains mandatory. Moving the UX is not a
substitute for that evidence.
