# Compiler compatibility profile for standalone `luc`

This M0 executable contract describes the existing pinned compiler boundary.
It is not an installer, a `luc` implementation, a frozen registry manifest/lock
schema, or completion of M7. The profile and fixtures let later adapters detect
compiler/linking changes instead of silently depending on `PATH` or editing a
language repository during its audit.

`compiler-profiles/pinned-v1.json` binds Base source
`162ff10fce15997abe38337029069971643614b2` and Luce source
`88d0e5d1847b489c0c3fb44425e8f56ee3bcc033`. Initial hosts are macOS arm64 and Linux
x86-64. CI checks the exact clean source revisions and bootstraps into this
repository's ignored build directory. Explicit local compiler paths must point to
trusted builds of those revisions; the test does not cryptographically attest that
an arbitrary supplied executable came from the stated source. Future distributed
toolchains also need signed binary/stdlib/target provenance and verification.

## Authoritative inputs and compiler protocols

The current compilers read `luce.toml`; the separate TOML/YAML and `luc.lock` design
decision remains open. These fixtures do not rewrite user projects or settle it
by introducing a second authoritative manifest. Their observed contract follows
the pinned Base [package documentation](https://github.com/dymokomi/luce-base/blob/162ff10fce15997abe38337029069971643614b2/docs/PACKAGE-IMPORTS.md).

| Boundary | Required interpretation |
| --- | --- |
| `luce-base resolve` | `luce-base-module-v1`, then kind/name/path/root; every field NUL-terminated |
| `luce-base dependencies` | `luce-base-dependencies-v3`, then NUL-terminated tagged triples; source, alias, package owner and native inputs |
| `luce-base native-inputs` | Same dependency protocol, containing-manifest native inputs only; accepts Base or Luce entry paths |
| `luce build` | Select Base explicitly with `LUCE_BASE`; use argument vectors, never a shell command string |
| Base application `main` | Argument span includes executable name at index zero |
| Luce application `main` | Argument list contains user arguments only; do not manually strip another argument in `luc` |

Paths are not newline-delimited. Harness unit tests retain whitespace/newlines and
reject wrong protocol versions, missing terminators, invalid UTF-8, incomplete or
duplicate records and unknown tags. A production adapter still needs bounded I/O,
timeouts/cancellation, capability negotiation, argument validation and diagnostics;
the Python harness is not that production implementation.

Package identity, export name and source path are distinct. The fixture contains
`profile_project -> profile_wrapper -> profile_scalars`. Two exports of the same
scalar module must preserve one nominal `Number` type; a different source module
with the same declaration spelling must not become interchangeable. Equal numeric
error ordinals in the three packages must remain different `ErrorCode` identities.
The actual built executables check this, not only a JSON description.

The two native C files are tiny **test-only linker sentinels**, not registry or
package-engine implementations. They prove that native sources declared by two
transitive packages are compiled/linked, that spaces in paths survive and that
duplicate `m` library inputs merge. Other native-input kinds, static archive order,
framework/pkg-config behavior, target cross-compilation and arbitrary external
inputs are not covered by these sentinels. The infrastructure's Base-only runtime
rule remains unchanged.

## Reproduction and covered behavior

```sh
python3 tools/bootstrap_compilers.py
python3 tests/test_compiler_protocols.py
python3 tests/check_compilers.py
```

Use `--base PATH --luce PATH` to reuse trusted pinned compilers and `--mode native0`
for a quick run. The complete profile rebuilds and executes both language entries
in native optimization levels 0–3 and C debug/release. It then repeats after moving
the entire source/dependency tree so the original absolute native paths no longer
exist. Paths and arguments include spaces, semicolons and literal dollar signs.
All fixture source/manifest hashes must remain unchanged; scratch trees/executables
are temporary and cleaned on ordinary completion or failure.

The fixture also emits a diagnostic Base package, checks its original module-owner
metadata, rebuilds it while native inputs are available and verifies the same
behavior. Emitted `[module_packages]` uses unquoted dotted keys: full TOML represents
them as nested maps, while the compiler's reader treats them as canonical module
names. Do not use naive dictionary keys to reinterpret ownership. This is another
reason to share a tested normalized model rather than duplicate ad hoc parsers.

The diagnostic package retains absolute native-source paths. **It is not a portable
release archive**. Source-tree relocation passes because the original manifests
retain relative paths and the compilers regenerate build inputs; this is not proof
that `--emit=base` artifacts can be installed on another machine unchanged.

Negative builds reject mismatched dependency keys, missing dependency directories,
competing package exports, local/export collisions and different nominal source
types. A rejection must be a normal failed process with a relevant diagnostic and
no executable, never a signal or sanitizer report. Compiler-protocol harness tests
and positive builds remain separate from these negative cases.

One current interop restriction is deliberately recorded: a Base function returning
`ErrorCode` directly is absent from the Luce bridge, although exported error-code
constants and normal fallible calls remain usable. The positive fixture checks
owner identity through supported constants/native validation, while an explicit
negative Luce probe checks that the unavailable function remains unavailable. This
is a compatibility limitation, not an installer failure or a language patch. Future
profiles should update this probe when the language team changes the boundary.

No network packages, credentials or live services are used. These are local-source
compatibility checks, not OS-enforced offline, TLS, signed-cache, resolver or registry
tests. They do not prove the final `luc init/add/sync/build` journey. Those commands,
verified downloads, hostile archives, concurrent install recovery and locked/offline/
relocated-cache acceptance still require M2c/M3b/M6/M7 implementation and evidence.

## Initial local evidence — 2026-09-14 PDT / 2026-09-15 UTC

Fresh local bootstrap from both clean pinned sources passed, followed by all
70 profile commands on macOS arm64. This includes 24 source-tree build/run pairs
across two languages, six modes and two locations, one Luce emission followed by
a Base build/run,
eight protocol invocations, ten negative builds and the unavailable-interop probe.
Five profile/protocol unit tests and the existing eight tracker tests also passed.
Logs are retained under ignored `build/compiler-*-local.log` and
`build/compiler-profile-unit.log`. The initial fixture assumptions about main
arguments, TOML dotted-key lookup and missing-directory diagnostic text were corrected
before this final run; earlier incomplete runs are not counted as full passes.

Source/test revision `2ae259245bc2123ed612b464c2eb1ffdcf82bbc6` also passed the
[dedicated compiler CI](https://github.com/dymokomi/luce-pkg-server/actions/runs/34932787760)
on macOS 15 arm64 and Ubuntu 24.04 x86-64. Both retained logs contain all 24
source-tree build/run pairs, ten negative builds and the successful 70-command
completion record. Fresh pinned bootstraps and five profile/protocol unit tests
passed in both jobs. The separate eight-test
[tracker CI](https://github.com/dymokomi/luce-pkg-server/actions/runs/34932787734)
also passed on both hosts. These runs verify this exact source revision, not a
future compiler update or an arbitrary installed toolchain. No VPS compiler
installation or live-service test is part of this local-source profile.
