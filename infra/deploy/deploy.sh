#!/usr/bin/env bash
# Pull main and rebuild the stack. Invoked by groknet-deploy.py; safe to run by hand:
#   bash ~/containers/groknet/infra/deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "$(date -u +%FT%TZ) [deploy] fetching origin/main"
git fetch --quiet origin main
git reset --hard --quiet origin/main
echo "$(date -u +%FT%TZ) [deploy] now at $(git rev-parse --short HEAD): $(git log -1 --pretty=%s)"

echo "$(date -u +%FT%TZ) [deploy] docker compose up --build"
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null || true
echo "$(date -u +%FT%TZ) [deploy] done"
