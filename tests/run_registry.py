#!/usr/bin/env python3
"""Build the loopback registry and run proxy/invite tests in every pinned mode."""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MODES = {f"native{i}": ["--native", "--opt", str(i)] for i in range(4)}
MODES.update({"c": ["--backend=c"], "c-release": ["--backend=c", "--release"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=[*MODES, "all"], default="all")
    parser.add_argument("--base", type=Path, default=ROOT / "build/toolchain/luce-base")
    args = parser.parse_args()
    if not args.base.is_file():
        raise SystemExit("Need a pinned luce-base at build/toolchain/luce-base")
    environment = dict(os.environ, LUCE_BASE=str(args.base.resolve()))
    environment.setdefault("LUCE_STD", str(ROOT.parent / "luce-base/src/std"))
    environment.setdefault("LUCE_CACHE", str(ROOT / "build/cache"))
    def run(command, timeout=180):
        subprocess.run([str(a) for a in command], cwd=ROOT, env=environment, check=True, timeout=timeout)
    for mode, flags in MODES.items():
        if args.mode not in (mode, "all"): continue
        if mode == "c":
            # Two intentionally concurrent Argon2 registrations can exceed the
            # ordinary per-request guard in the unoptimized generated-C build on
            # hosted runners. This is a correctness matrix, not a latency SLA.
            environment["LUCE_TEST_HTTP_TIMEOUT"] = "60"
        else:
            environment.pop("LUCE_TEST_HTTP_TIMEOUT", None)
        output = ROOT / "build" / mode
        output.mkdir(parents=True, exist_ok=True)
        print(f"MODE {mode}", flush=True)
        run([args.base.resolve(), "build", ROOT / "src/luce_pkg_server/registry.lucb", *flags, "-o", output / "registry"])
        run([args.base.resolve(), "build", ROOT / "src/luce_pkg_server/admin.lucb", *flags, "-o", output / "admin"])
        run([args.base.resolve(), "build", ROOT / "tests/http_auth.lucb", *flags, "-o", output / "http-auth"])
        run([args.base.resolve(), "build", ROOT / "tests/rate_limit.lucb", *flags, "-o", output / "rate-limit"])
        run([args.base.resolve(), "build", ROOT / "tests/account_fixture.lucb", *flags, "-o", output / "account-fixture"])
        run([args.base.resolve(), "build", ROOT / "tests/legacy_fixture.lucb", *flags, "-o", output / "legacy-fixture"])
        # Unoptimized generated C executes the complete native ML-DSA/Argon2
        # integration matrix substantially more slowly than the native backend.
        # Hosted x86-64 Linux has exceeded seven minutes after completing Git,
        # release and both native-client transfers. Keep every assertion and only
        # widen this per-process wall-clock guard within the 75-minute job bound.
        timeout = 600 if mode == "c" else 240
        run([output / "http-auth"])
        run([output / "rate-limit"])
        run([os.environ.get("PYTHON", "python3"), str(ROOT / "tests/check_accounts.py"), output / "registry", output / "account-fixture"], timeout=timeout)
        run([os.environ.get("PYTHON", "python3"), str(ROOT / "tests/admin.py"), output / "admin", output / "registry"], timeout=timeout)
        run([os.environ.get("PYTHON", "python3"), str(ROOT / "tests/deployment.py"), output / "admin"], timeout=timeout)
        run([os.environ.get("PYTHON", "python3"), str(ROOT / "tests/storage.py"), output / "registry", output / "admin", output / "account-fixture"], timeout=timeout)
        run([os.environ.get("PYTHON", "python3"), str(ROOT / "tests/migration.py"), output / "registry", output / "admin", output / "legacy-fixture"], timeout=timeout)
        print(f"PASS {mode}", flush=True)
    print("PASS all selected compiler modes", flush=True)


if __name__ == "__main__":
    main()
