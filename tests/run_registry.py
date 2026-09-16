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
    def run(command):
        subprocess.run([str(a) for a in command], cwd=ROOT, env=environment, check=True, timeout=180)
    for mode, flags in MODES.items():
        if args.mode not in (mode, "all"): continue
        output = ROOT / "build" / mode
        output.mkdir(parents=True, exist_ok=True)
        print(f"MODE {mode}", flush=True)
        run([args.base.resolve(), "build", ROOT / "src/luce_pkg_server/registry.lucb", *flags, "-o", output / "registry"])
        run([os.environ.get("PYTHON", "python3"), str(ROOT / "tests/check_registry.py"), output / "registry"])
        print(f"PASS {mode}", flush=True)
    print("PASS all selected compiler modes", flush=True)


if __name__ == "__main__":
    main()
