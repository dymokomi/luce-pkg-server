#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: backup.sh DATA_DIR DATABASE ADMIN ENVIRONMENT_FILE NEW_BACKUP_DIR" >&2
  exit 2
fi

data_dir=$1
database=$2
admin=$3
environment_file=$4
destination=$5
# The public site is not backed up: `luce-pkg-admin rebuild-site` writes it from the
# database, and restore.sh does that.

for path in "$data_dir" "$database" "$admin" "$environment_file" "$destination"; do
  [[ "$path" = /* ]] || { echo "all paths must be absolute" >&2; exit 2; }
done
[[ "$data_dir" != / && "$destination" != / ]] || { echo "refusing broad path" >&2; exit 2; }
[[ -d "$data_dir" && -f "$database" && -x "$admin" && -f "$environment_file" ]] || {
  echo "missing backup input" >&2
  exit 1
}
[[ ! -e "${database}.sock" ]] || { echo "registry must be stopped before backup" >&2; exit 1; }
[[ ! -e "$destination" ]] || { echo "backup destination already exists" >&2; exit 1; }
parent=$(dirname "$destination")
[[ -d "$parent" ]] || { echo "backup parent does not exist" >&2; exit 1; }

set -a
# Root-owned 0600 file containing only LUCE_REGISTRY_STORE_TOKEN and
# LUCE_REGISTRY_ORIGIN assignments.
source "$environment_file"
set +a
# As root, checkpoint as the owner of the data directory: a root-run checkpoint would
# leave a root-owned database and snapshot that the service can no longer open.
if [[ $EUID -eq 0 ]]; then
  owner=$(stat -c %U "$data_dir")
  group=$(stat -c %G "$data_dir")
  (cd / && setpriv --reuid "$owner" --regid "$group" --clear-groups \
    env -i PATH=/usr/bin LUCE_REGISTRY_STORE_TOKEN="$LUCE_REGISTRY_STORE_TOKEN" \
    "$admin" checkpoint "$database" >/dev/null)
else
  "$admin" checkpoint "$database" >/dev/null
fi
unset LUCE_REGISTRY_STORE_TOKEN LUCE_REGISTRY_ORIGIN

staging=$(mktemp -d "$parent/.luce-pkg-backup.XXXXXX")
cleanup() { [[ -z "${staging:-}" ]] || rm -rf -- "$staging"; }
trap cleanup EXIT
mkdir "$staging/state"
cp -a "$data_dir/." "$staging/state/"
(
  cd "$staging/state"
  if command -v sha256sum >/dev/null 2>&1; then
    find . -type f -print | LC_ALL=C sort | while IFS= read -r file; do sha256sum "$file"; done
  else
    find . -type f -print | LC_ALL=C sort | while IFS= read -r file; do shasum -a 256 "$file"; done
  fi
) >"$staging/SHA256SUMS"
chmod -R go-rwx "$staging"
mv "$staging" "$destination"
staging=
trap - EXIT
echo "$destination"
