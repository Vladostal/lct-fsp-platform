#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
ROOT=/home/fedya/fsp-platform
incoming=${1:?validated release directory required}
sha=${2:?commit required}
[[ $sha =~ ^[0-9a-f]{40}$ ]]
[[ $incoming == "$ROOT/incoming/"*/release ]]
mkdir -p "$ROOT/releases" "$ROOT/backups" "$ROOT/state"
exec 9>"$ROOT/state/deploy.lock"
flock -w 1800 9
schema=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["schema"])' "$incoming/manifest.json")
if [[ -f $ROOT/state/schema-fingerprint ]]; then
  [[ $(cat "$ROOT/state/schema-fingerprint") == "$schema" ]] || { echo 'Schema changed: reviewed migration required.'; exit 1; }
fi
previous=$(readlink -f "$ROOT/current" || true)
release="$ROOT/releases/$sha"
if [[ -n $previous && -f $previous/manifest.json ]]; then
  python3 - "$previous/manifest.json" "$incoming/manifest.json" <<'PY'
import json, sys
old, new = (json.load(open(p)) for p in sys.argv[1:])
if old['schema'] != new['schema']:
    raise SystemExit('Schema changed: automatic deployment stopped. Prepare and apply a reviewed migration first.')
PY
fi
if [[ -d $release ]]; then
  cmp "$release/manifest.json" "$incoming/manifest.json"
else
  mv "$incoming" "$release"
fi
ln -sfn "$ROOT/shared/.env" "$release/.env"
printf 'FSP_API_IMAGE=fsp-podbor-backend:%s\nFSP_WEB_IMAGE=fsp-podbor-frontend:%s\n' "$sha" "$sha" > "$release/.images.env"
compose() {
  docker compose -p fsp-platform --env-file "$ROOT/shared/.env" --env-file "$1/.images.env" \
    -f "$1/compose.production.yml" "${@:2}"
}
compose "$release" config --quiet
# Only this project's images are loaded. No global prune, stop or daemon reconfiguration.
for component in backend frontend; do
  if ! docker image inspect "fsp-podbor-$component:$sha" >/dev/null 2>&1; then
    gzip -dc "$release/images/$component.tar.gz" | docker image load
  fi
  docker image inspect "fsp-podbor-$component:$sha" >/dev/null
 done
if [[ -n $previous && -f $previous/.images.env ]]; then
  compose "$previous" exec -T db pg_dump -U app -d app -Fc > "$ROOT/backups/$(date -u +%Y%m%dT%H%M%SZ)-$sha.dump"
fi
rollback() {
  result=$?
  trap - ERR
  echo "Deployment failed (exit $result)."
  if [[ -n $previous && -f $previous/.images.env ]]; then
    echo 'Restoring previous application images; database backup is retained for manual recovery.'
    compose "$previous" up -d --wait --wait-timeout 180 db mailpit api web caddy || true
  fi
  exit "$result"
}
trap rollback ERR
compose "$release" up -d --wait --wait-timeout 150 db mailpit
compose "$release" run --rm --no-deps migrate
printf '%s\n' "$schema" > "$ROOT/state/schema-fingerprint"
compose "$release" up -d --wait --wait-timeout 180 api web caddy
url=$(python3 - "$ROOT/shared/.env" <<'PY'
import sys
for line in open(sys.argv[1]):
    if line.startswith('PUBLIC_BASE_URL='):
        print(line.strip().split('=', 1)[1]); break
else:
    raise SystemExit('PUBLIC_BASE_URL missing')
PY
)
ready=false
for attempt in $(seq 1 60); do
  if curl --fail --silent --show-error --max-time 10 "$url/api/v1/health" >/dev/null \
    && curl --fail --silent --max-time 10 "$url/healthz" >/dev/null; then
    ready=true
    break
  fi
  sleep 3
 done
[[ $ready == true ]]
ln -sfn "$release" "$ROOT/current.next"
mv -Tf "$ROOT/current.next" "$ROOT/current"
printf '%s\n' "$sha" > "$ROOT/state/deployed-sha"
trap - ERR
# Archives remain in GitHub; retain runtime releases and images for rollback without duplicating large blobs.
rm -f "$release/images/backend.tar.gz" "$release/images/frontend.tar.gz"
echo "Deployed $sha at $url"
