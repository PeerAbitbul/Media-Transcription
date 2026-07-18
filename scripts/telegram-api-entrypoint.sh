#!/bin/sh
# Entrypoint for the self-hosted local Telegram Bot API server.
#
# The api_id / api_hash are entered once in the web UI and written by the API
# service to a small env file on the shared ./data volume. This script waits for
# that file to appear, reads the credentials, and launches the server. Because
# the file lives on a persistent volume, this works across restarts with no
# re-entry — configure once, and it comes back up on its own.
set -eu

CREDS_FILE="${TELEGRAM_CREDS_FILE:-/data/telegram-api.env}"

echo "[telegram-bot-api] waiting for credentials at ${CREDS_FILE} (set them in the web UI)…"
while [ ! -f "$CREDS_FILE" ]; do
  sleep 3
done

# File defines API_ID and API_HASH.
# shellcheck disable=SC1090
. "$CREDS_FILE"

if [ -z "${API_ID:-}" ] || [ -z "${API_HASH:-}" ]; then
  echo "[telegram-bot-api] credentials file present but incomplete; waiting for a valid save…"
  while [ -z "${API_ID:-}" ] || [ -z "${API_HASH:-}" ]; do
    sleep 3
    # shellcheck disable=SC1090
    . "$CREDS_FILE"
  done
fi

echo "[telegram-bot-api] starting local server (api_id=${API_ID}) on :8081"
exec telegram-bot-api \
  --local \
  --api-id="$API_ID" \
  --api-hash="$API_HASH" \
  --http-port=8081 \
  --dir=/var/lib/telegram-bot-api \
  --temp-dir=/var/lib/telegram-bot-api/tmp \
  --verbosity=1
