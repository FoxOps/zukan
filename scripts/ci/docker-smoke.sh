#!/usr/bin/env bash
# Start a Zukan image against a PostgreSQL server and check it really works:
# migrations, API, web UI, admin bootstrap, login, game plugins.
#
#   scripts/ci/docker-smoke.sh IMAGE [DATABASE_URL]
#
# The container uses the host network, so DATABASE_URL points at the host (CI service
# container or local dev database). Port 8000 must be free.
set -euo pipefail

image=${1:?usage: docker-smoke.sh IMAGE [DATABASE_URL]}
database_url=${2:-postgresql+asyncpg://tcg:tcg@localhost:5432/tcg}
name=zukan-smoke-$$
base=http://localhost:8000

cleanup() {
    status=$?
    if [ $status -ne 0 ]; then
        echo "--- container logs ---"
        docker logs "$name" 2>&1 | tail -100 || true
    fi
    docker rm -f "$name" >/dev/null 2>&1 || true
    exit $status
}
trap cleanup EXIT

docker run -d --name "$name" --network host \
    -e TCG_DATABASE_URL="$database_url" \
    -e TCG_SECRET_KEY="smoke-test-secret-key-that-is-long-enough" \
    -e TCG_COOKIE_SECURE=false \
    "$image" >/dev/null

echo "Waiting for the API..."
for _ in $(seq 1 60); do
    if curl -sf "$base/api/health" >/dev/null; then break; fi
    sleep 2
done
curl -sf "$base/api/health" | grep -q '"ok"' || { echo "API did not start"; exit 1; }

echo "Web UI is served"
curl -sf "$base/collection" | grep -q "<title>Zukan</title>"
asset=$(curl -sf "$base/" | grep -o '/assets/index-[^"]*\.js' | head -1)
curl -sf -o /dev/null "$base$asset"

echo "Default administrator can sign in"
curl -sf "$base/api/auth/login" -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"changeme"}' | grep -q access_token

echo "Admin bootstrap and login"
docker exec -e TCG_ADMIN_PASSWORD=smoke-password "$name" zukan create-admin smoke >/dev/null
token=$(curl -sf "$base/api/auth/login" -H 'Content-Type: application/json' \
    -d '{"username":"smoke","password":"smoke-password"}' |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

echo "Game plugins are installed"
games=$(curl -sf "$base/api/games" -H "Authorization: Bearer $token")
for game in mtg pokemon sorcery; do
    echo "$games" | grep -q "\"id\":\"$game\"" || { echo "missing game $game"; exit 1; }
done

echo "Smoke test passed for $image"
