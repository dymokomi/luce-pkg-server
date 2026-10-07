#!/bin/sh
# This package's own tests (luce-base docs/CI.md): the programs under tests/, built with
# the development toolchain on PATH (luce-base tools/toolchain.py).
set -eu
cd "$(dirname "$0")"
base=$(command -v luce-base)
luce=$(command -v luce)
python3 tests/run_registry.py --mode native3 --base "$base"
exec python3 tests/run_repositories.py --mode native3 --base "$base" "$@"
