#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 && $# -ne 5 ]]; then
  echo "usage: restore.sh BACKUP_DIR NEW_DATA_DIR ADMIN ENVIRONMENT_FILE [NEW_SITE_DIR]" >&2
  exit 2
fi

backup=$1
destination=$2
admin=$3
environment_file=$4
new_site=${5:-}
if [[ -n "$new_site" ]]; then
  [[ "$new_site" = /* && "$new_site" != / ]] || { echo "site path must be absolute" >&2; exit 2; }
  [[ -d "$backup/site" && -f "$backup/SITE_SHA256SUMS" ]] || { echo "backup holds no site files" >&2; exit 1; }
  [[ ! -e "$new_site" ]] || { echo "site restore destination already exists" >&2; exit 1; }
  [[ -d "$(dirname "$new_site")" ]] || { echo "site restore parent does not exist" >&2; exit 1; }
  (
    cd "$backup/site"
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum -c "$backup/SITE_SHA256SUMS"
    else
      shasum -a 256 -c "$backup/SITE_SHA256SUMS"
    fi
  ) >/dev/null
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
unset LUCE_REGISTRY_STORE_TOKEN LUCE_REGISTRY_ORIGIN
if [[ -n "$new_site" ]]; then
  site_staging=$(mktemp -d "$(dirname "$new_site")/.luce-pkg-site-restore.XXXXXX")
  cp -a "$backup/site/." "$site_staging/"
  mv "$site_staging" "$new_site"
fi
mv "$staging" "$destination"
staging=
trap - EXIT
echo "$destination"
