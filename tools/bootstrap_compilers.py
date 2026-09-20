#!/usr/bin/env python3
"""Build the compatibility profile's pinned sibling sources without editing them."""
import json
import os
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/toolchain"


def main():
    profile = json.loads((ROOT / "compiler-profiles/pinned-v1.json").read_text())
    host = {("Darwin", "arm64"): "arm64-macos", ("Linux", "x86_64"): "x86_64-linux"}.get((platform.system(), platform.machine()))
    if host not in profile["hosts"]:
        raise SystemExit("unsupported compiler-profile host")
    base, luce = ROOT.parent / "luce-base", ROOT.parent / "luce"
    for source, expected in [(base, profile["base_source"]), (luce, profile["luce_source"])]:
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        if actual != expected: raise SystemExit(f"source pin mismatch: {source}")
        if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"]):
            raise SystemExit(f"dirty compiler source: {source}")
    OUT.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["LUCE_STD"] = str(base / "src/std")

    def run(command):
        subprocess.run([str(arg) for arg in command], cwd=ROOT, env=environment,
                       check=True, timeout=180)

    run([os.environ.get("CC", "cc"), "-std=gnu11", "-O2", "-w", "-fno-strict-aliasing",
         "-I", base / "runtime", base / "bootstrap" / f"luce-base-{host}.c",
         base / "runtime/lucb_rt.c", "-lm", "-pthread", "-o", OUT / "stage0"])
    run([OUT / "stage0", "build", base / "src/main.lucb", "--native", "-o", OUT / "luce-base"])
    run([OUT / "luce-base", "build", luce / "src/main.lucb", "--native", "-o", OUT / "luce"])


if __name__ == "__main__": main()
