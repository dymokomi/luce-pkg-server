#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: build-release.sh LUCE_BASE SOURCE_COMMIT NEW_OUTPUT_DIR" >&2
  exit 2
fi

compiler=$1
source_commit=$2
destination=$3

for path in "$compiler" "$destination"; do
  [[ "$path" = /* ]] || { echo "compiler and output paths must be absolute" >&2; exit 2; }
done
[[ "$destination" != / ]] || { echo "refusing broad output path" >&2; exit 2; }
[[ -x "$compiler" ]] || { echo "luce-base compiler is not executable" >&2; exit 1; }
[[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] || { echo "source commit must be 40 lowercase hex characters" >&2; exit 2; }
[[ "$(uname -s)" = Linux && "$(uname -m)" = x86_64 ]] || {
  echo "release bundles must be built natively on x86_64 Linux" >&2
  exit 1
}

root=$(cd "$(dirname "$0")/.." && pwd -P)
[[ "$(git -C "$root" rev-parse HEAD)" = "$source_commit" ]] || {
  echo "source commit does not match the checked-out revision" >&2
  exit 1
}
git -C "$root" diff --quiet --
git -C "$root" diff --cached --quiet --
[[ ! -e "$destination" ]] || { echo "release destination already exists" >&2; exit 1; }
parent=$(dirname "$destination")
[[ -d "$parent" ]] || { echo "release destination parent does not exist" >&2; exit 1; }

standard=${LUCE_STD:-"$root/../luce-base/src/std"}
cache=${LUCE_CACHE:-"$root/build/cache"}
[[ -d "$standard" ]] || { echo "LUCE_STD does not name the pinned standard library" >&2; exit 1; }
mkdir -p "$cache"

staging=$(mktemp -d "$parent/.luce-pkg-release.XXXXXX")
cleanup() { [[ -z "${staging:-}" ]] || rm -rf -- "$staging"; }
trap cleanup EXIT

LUCE_STD=$standard LUCE_CACHE=$cache "$compiler" build \
  "$root/src/luce_pkg_server/registry.lucb" --native --release \
  -o "$staging/luce-pkg-server"
LUCE_STD=$standard LUCE_CACHE=$cache "$compiler" build \
  "$root/src/luce_pkg_server/admin.lucb" --native --release \
  -o "$staging/luce-pkg-admin"

install -m 0644 "$root/deploy/luce-pkg-server.service" "$staging/"
install -m 0644 "$root/deploy/Caddyfile" "$staging/"
install -m 0644 "$root/deploy/README.md" "$staging/DEPLOYMENT.md"
install -m 0755 "$root/deploy/backup.sh" "$staging/"
install -m 0755 "$root/deploy/restore.sh" "$staging/"
mkdir "$staging/site-assets" "$staging/host"
install -m 0644 "$root"/deploy/host/* "$staging/host/"
install -m 0644 "$root"/deploy/site-assets/* "$staging/site-assets/"
printf '%s\n' "$source_commit" >"$staging/SOURCE_COMMIT"

: >"$staging/DEPENDENCY_PINS"
for pin in "$root"/bootstrap/*; do
  name=$(basename "$pin")
  revision=$(tr -d '\n' <"$pin")
  [[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo "invalid dependency pin: $name" >&2; exit 1; }
  printf '%s %s\n' "$name" "$revision" >>"$staging/DEPENDENCY_PINS"
done

(
  cd "$staging"
  find . -type f ! -name SHA256SUMS -print | LC_ALL=C sort | while IFS= read -r file; do
    sha256sum "$file"
  done
) >"$staging/SHA256SUMS"
chmod -R go-w "$staging"
mv "$staging" "$destination"
staging=
trap - EXIT
printf '%s\n' "$destination"
