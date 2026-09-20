#!/usr/bin/env python3
"""Build pinned sibling compilers into this package; never edit their sources."""
import os
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "toolchain"
ENV = dict(os.environ)
ENV.setdefault("LUCE_STD", str(ROOT.parent / "luce-base/src/std"))
ENV.setdefault("LUCE_CACHE", str(ROOT / "build/cache"))


def run(args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, env=ENV, check=True, timeout=600)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base, luce = ROOT.parent / "luce-base", ROOT.parent / "luce"
    host = {("Darwin", "arm64"): "arm64-macos",
            ("Linux", "x86_64"): "x86_64-linux"}.get((platform.system(), platform.machine()))
    if not host:
        raise SystemExit("Use explicit compiler paths on this platform.")
    crypto = ROOT.parent / "luce-crypto"
    for source, pin in ((base, "BASE"), (luce, "LUCE"), (crypto, "CRYPTO"),
                        (ROOT.parent / "luce-tls", "TLS"),
                        (ROOT.parent / "luce-prism", "PRISM"),
                        (ROOT.parent / "luce-server", "SERVER"),
                        (ROOT.parent / "luce-db", "DB"),
                        (ROOT.parent / "luce-auth", "AUTH"),
                        (ROOT.parent / "luce-pkg", "PKG"),
                        (ROOT.parent / "luce-json", "JSON"),
                        (ROOT.parent / "luce-git", "GIT"),
                        (ROOT.parent / "luce-http-client", "HTTP_CLIENT"),
                        (ROOT.parent / "luce-compress", "COMPRESS")):
        expected = (ROOT / "bootstrap" / pin).read_text().strip()
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"]):
            raise SystemExit(f"dirty source: {source}")
        if actual != expected:
            raise SystemExit(f"{source}: expected {expected}, found {actual}")
    run([os.environ.get("CC", "cc"), "-std=gnu11", "-O2", "-w", "-fno-strict-aliasing",
         "-I", base / "runtime", base / "bootstrap" / f"luce-base-{host}.c",
         base / "runtime/lucb_rt.c", "-lm", "-pthread", "-o", OUT / "stage0"])
    run([OUT / "stage0", "build", base / "src/main.lucb", "--native", "-o", OUT / "luce-base"])
    run([OUT / "luce-base", "build", luce / "src/main.lucb", "--native", "-o", OUT / "luce"])


if __name__ == "__main__":
    main()
