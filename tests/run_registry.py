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
        output = ROOT / "build" / mode
        output.mkdir(parents=True, exist_ok=True)
        print(f"MODE {mode}", flush=True)
        run([args.base.resolve(), "build", ROOT / "src/luce_pkg_server/registry.lucb", *flags, "-o", output / "registry"])
        run([args.base.resolve(), "build", ROOT / "tests/account_fixture.lucb", *flags, "-o", output / "account-fixture"])
        run([args.base.resolve(), "build", ROOT / "tests/client/native_transfer.lucb", *flags, "-o", output / "native-transfer"])
        # Unoptimized generated C executes the complete native ML-DSA/Argon2
        # integration matrix substantially more slowly than the native backend.
        # Keep the same assertions and only widen the process wall-clock guard.
        timeout = 420 if mode == "c" else 240
        run([os.environ.get("PYTHON", "python3"), str(ROOT / "tests/check_accounts.py"), output / "registry", output / "account-fixture", output / "native-transfer"], timeout=timeout)
        print(f"PASS {mode}", flush=True)
    print("PASS all selected compiler modes", flush=True)


if __name__ == "__main__":
    main()
