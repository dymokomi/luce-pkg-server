#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 && $# -ne 5 ]]; then
  echo "usage: restore.sh BACKUP_DIR NEW_DATA_DIR ADMIN ENVIRONMENT_FILE [NEW_SITE_DIR]" >&2
  echo "NEW_SITE_DIR is rebuilt from the restored database, with the bundle's site-assets" >&2
  exit 2
fi

backup=$1
destination=$2
admin=$3
environment_file=$4
new_site=${5:-}
if [[ -n "$new_site" ]]; then
  [[ "$new_site" = /* && "$new_site" != / ]] || { echo "site path must be absolute" >&2; exit 2; }
  [[ ! -e "$new_site" ]] || { echo "site restore destination already exists" >&2; exit 1; }
  [[ -d "$(dirname "$new_site")" ]] || { echo "site restore parent does not exist" >&2; exit 1; }
fi
for path in "$backup" "$destination" "$admin" "$environment_file"; do
  [[ "$path" = /* ]] || { echo "all paths must be absolute" >&2; exit 2; }
done
[[ "$backup" != / && "$destination" != / ]] || { echo "refusing broad path" >&2; exit 2; }
[[ -d "$backup/state" && -f "$backup/SHA256SUMS" && -x "$admin" && -f "$environment_file" ]] || {
  echo "missing restore input" >&2
  exit 1
}
[[ ! -e "$destination" ]] || { echo "restore destination already exists" >&2; exit 1; }
(
  cd "$backup/state"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c "$backup/SHA256SUMS"
  else
    shasum -a 256 -c "$backup/SHA256SUMS"
  fi
) >/dev/null
parent=$(dirname "$destination")
[[ -d "$parent" ]] || { echo "restore parent does not exist" >&2; exit 1; }
staging=$(mktemp -d "$parent/.luce-pkg-restore.XXXXXX")
cleanup() { [[ -z "${staging:-}" ]] || rm -rf -- "$staging"; }
trap cleanup EXIT
cp -a "$backup/state/." "$staging/"
set -a
source "$environment_file"
set +a
"$admin" checkpoint "$staging/registry.db" >/dev/null
if [[ -n "$new_site" ]]; then
  # Rebuilt beside its final name, then moved there whole.
  site_staging="$(dirname "$new_site")/.luce-pkg-site-restore.$$"
  site_cleanup() { rm -rf -- "$site_staging"; }
  trap 'cleanup; site_cleanup' EXIT
  "$admin" rebuild-site "$staging/registry.db" "$site_staging" >/dev/null
  assets="$(dirname "$admin")/site-assets"
  if [[ -d "$assets" ]]; then
    mkdir "$site_staging/assets"
    cp -a "$assets/." "$site_staging/assets/"
  fi
  mv "$site_staging" "$new_site"
fi
unset LUCE_REGISTRY_STORE_TOKEN LUCE_REGISTRY_ORIGIN
mv "$staging" "$destination"
staging=
trap - EXIT
echo "$destination"
