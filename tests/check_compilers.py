#!/usr/bin/env python3
"""Real pinned-compiler compatibility; not an installer, resolver or registry test."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/compiler_fixture"
PROFILE = ROOT / "compiler-profiles/pinned-v1.json"
MODES = {f"native{i}": ["--native", "--opt", str(i)] for i in range(4)}
MODES.update({"c": ["--backend=c"], "c-release": ["--backend=c", "--release"]})
ARGUMENTS = ["argument with spaces", "; literal dollar$"]


def fields(data, version):
    assert data.endswith(b"\0"), "unterminated compiler protocol"
    result = data[:-1].decode("utf-8").split("\0")
    assert result[0] == version, "unsupported compiler protocol"
    return result[1:]


def records(data, version):
    result = fields(data, version)
    assert len(result) % 3 == 0, "incomplete dependency record"
    triples = [tuple(result[index:index + 3]) for index in range(0, len(result), 3)]
    assert len(triples) == len(set(triples)), "duplicate compiler record"
    assert all(kind in ["source", "alias", "package", "native"] for kind, _, _ in triples)
    return triples


def snapshot(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def check(base, luce, modes):
    base, luce = Path(base).resolve(), Path(luce).resolve()
    profile = json.loads(PROFILE.read_text())
    assert profile["schema_version"] == 1 and profile["modes"] == list(MODES)
    environment = dict(os.environ, LUCE_BASE=str(base))
    original_fixture = snapshot(FIXTURE)
    count = 0

    def run(command, reject=False, diagnostic=None):
        nonlocal count
        # No shell, inherited stdin or implicit compiler selection.
        result = subprocess.run([str(arg) for arg in command], env=environment,
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=180)
        count += 1
        if reject:
            assert result.returncode > 0, (command, result.returncode, result.stdout, result.stderr)
            if diagnostic is not None:
                assert diagnostic in result.stdout + result.stderr, (command, result.stdout, result.stderr)
        else:
            assert result.returncode == 0, (command, result.returncode, result.stdout, result.stderr)
        for marker in [b"AddressSanitizer", b"UndefinedBehaviorSanitizer", b"runtime error:"]:
            assert marker not in result.stderr, result.stderr
        return result.stdout

    with tempfile.TemporaryDirectory(prefix="luce-compiler-profile-") as temporary:
        scratch = Path(temporary).resolve()
        first = scratch / "first root ; dollar$"
        relocated = scratch / "relocated root ; dollar$"
        shutil.copytree(FIXTURE, first)
        baseline = snapshot(first)

        def protocol(root):
            entry = root / "project/src/main.lucb"
            api = root / "wrapper/src/profile_wrapper/api.lucb"
            scalar = root / "scalars/src/profile_scalars/value.lucb"
            resolved = fields(run([base, "resolve", entry, entry.parent, "profile_api", "--base"]), profile["resolve_protocol"])
            assert resolved == ["base", "profile_wrapper.api", str(api), str(api.parents[1])], resolved
            deps = records(run([base, "dependencies", entry]), profile["dependencies_protocol"])
            assert ("source", "profile_wrapper.api", str(api)) in deps
            assert ("source", "profile_scalars.value", str(scalar)) in deps
            assert ("alias", "profile_api", "profile_wrapper.api") in deps
            for public in ["profile_values", "profile_alias"]:
                assert ("alias", public, "profile_scalars.value") in deps
            for module, owner in [("main", "profile_project"), ("profile_wrapper.api", "profile_wrapper"), ("profile_scalars.value", "profile_scalars")]:
                assert ("package", module, owner) in deps, deps
            native = [(name, value) for kind, name, value in deps if kind == "native"]
            assert native.count(("libraries", "m")) == 1, native
            for package, name in [("wrapper", "wrapper.c"), ("scalars", "scalar.c")]:
                assert ("sources", str(root / package / "native inputs" / name)) in native, native
            direct = records(run([base, "native-inputs", root / "wrapper/src/profile_wrapper/api.lucb"]), profile["dependencies_protocol"])
            assert ("native", "sources", str(root / "wrapper/native inputs/wrapper.c")) in direct
            assert not any("scalar.c" in value for _, _, value in direct)
            assert records(run([base, "native-inputs", root / "project/src/main.luc"]), profile["dependencies_protocol"]) == []

        for root in [first, relocated]:
            if root == relocated:
                first.rename(relocated)
                assert not first.exists() and snapshot(relocated) == baseline
            protocol(root)
            for mode in modes:
                for compiler, suffix, language in [(base, "lucb", "base"), (luce, "luc", "luce")]:
                    executable = scratch / f"{root.name}-{mode}-{language} executable"
                    run([compiler, "build", root / f"project/src/main.{suffix}", *MODES[mode], "-o", executable])
                    assert run([executable, *ARGUMENTS]) == b"PASS compiler profile 42\n"
                    print(f"PASS {root.name} {mode} {language}", flush=True)
            assert snapshot(root) == baseline, "compiler changed source/manifest inputs"

        # Generated Base preserves module ownership, but its native paths are
        # absolute diagnostic references, not a portable source release.
        emitted = scratch / "diagnostic output"
        run([luce, "build", relocated / "project/src/main.luc", "--emit=base", "-o", emitted])
        emitted = emitted.with_name(emitted.name + ".base")
        generated = tomllib.loads((emitted / "luce.toml").read_text())
        # Canonical dotted module names are emitted as unquoted TOML keys; a
        # full TOML parser represents them as nested maps, unlike Base's reader.
        assert generated["module_packages"]["profile_scalars"]["value"] == "profile_scalars"
        assert generated["module_packages"]["profile_wrapper"]["api"] == "profile_wrapper"
        for package, name in [("wrapper", "wrapper.c"), ("scalars", "scalar.c")]:
            assert str(relocated / package / "native inputs" / name) in generated["native"]["sources"]
        executable = scratch / "emitted executable"
        run([base, "build", emitted / "main.lucb", "--native", "-o", executable])
        assert run([executable, *ARGUMENTS]) == b"PASS compiler profile 42\n"

        # Native ErrorCode-returning functions are currently absent from the Luce
        # bridge. Keep that restriction visible, not mistaken for installer damage.
        unsupported = relocated / "project/src/unsupported.luc"
        unsupported.write_text("import profile_api as api\npub func main(arguments: list[str]) -> int!:\n    let code = api.core_marker()\n    return 0\n")
        run([luce, "check", unsupported], reject=True, diagnostic=b"core_marker")
        unsupported.unlink()

        for mutation in ["dependency_key", "missing_dependency", "duplicate_export", "local_export", "different_nominal_type"]:
            bad = scratch / ("negative " + mutation)
            shutil.copytree(FIXTURE, bad)
            manifest = bad / "project/luce.toml"
            if mutation == "dependency_key":
                manifest.write_text(manifest.read_text().replace("profile_wrapper =", "wrong_name ="))
            elif mutation == "missing_dependency":
                manifest.write_text(manifest.read_text().replace('"../wrapper"', '"../missing"'))
            elif mutation == "duplicate_export":
                shutil.copytree(bad / "wrapper", bad / "other")
                other = bad / "other/luce.toml"
                other.write_text(other.read_text().replace('name = "profile_wrapper"', 'name = "profile_other"'))
                manifest.write_text(manifest.read_text() + 'profile_other = "../other"\n')
            elif mutation == "local_export":
                (bad / "project/src/profile_api.lucb").write_text("pub func answer() -> i64:\n    return 0\n")
            else:
                scalar = bad / "scalars/src/profile_scalars/value.lucb"
                (scalar.parent / "other.lucb").write_text(scalar.read_text().replace("package(73)", "package(74)"))
                manifest = bad / "scalars/luce.toml"
                manifest.write_text(manifest.read_text().replace('profile_alias = "profile_scalars.value"', 'profile_alias = "profile_scalars.other"'))
            for compiler, suffix, language in [(base, "lucb", "base"), (luce, "luc", "luce")]:
                executable = scratch / f"reject-{mutation}-{language}"
                expected = {"dependency_key": b"dependency key", "missing_dependency": b"filesystem path", "duplicate_export": b"more than one package", "local_export": b"conflicts with a local", "different_nominal_type": b"type"}[mutation]
                run([compiler, "build", bad / f"project/src/main.{suffix}", "--native", "-o", executable], reject=True, diagnostic=expected)
                assert not executable.exists(), "rejected graph produced an executable"
                print(f"PASS reject {mutation} {language}", flush=True)
        assert snapshot(FIXTURE) == original_fixture, "checked-in fixtures changed"
    print(f"PASS {count} compiler-profile commands; real imports, transitive native linking, identity, argv and relocation", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=ROOT / "build/toolchain/luce-base")
    parser.add_argument("--luce", type=Path, default=ROOT / "build/toolchain/luce")
    parser.add_argument("--mode", choices=[*MODES, "all"], default="all")
    args = parser.parse_args()
    check(args.base, args.luce, list(MODES) if args.mode == "all" else [args.mode])
