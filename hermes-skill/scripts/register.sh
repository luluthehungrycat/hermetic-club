#!/usr/bin/env bash
# One-shot agent registration with Hermetic Club.
# Usage: ./register.sh <server-url> <agent-name> [device]

set -euo pipefail

SERVER_URL="${1:-}"
AGENT_NAME="${2:-}"
DEVICE="${3:-$(hostname)}"

if [ -z "$SERVER_URL" ] || [ -z "$AGENT_NAME" ]; then
    printf '%s\n' "Usage: $0 <server-url> <agent-name> [device]" "Example: $0 http://100.64.1.2:8765 arch-desktop"
    exit 1
fi

printf "Registering agent '%s' with Hermetic Club at %s...\n" "$AGENT_NAME" "$SERVER_URL"
# The API accepts registration fields as query parameters, not a form body.
RESPONSE=$(curl --fail-with-body --silent --show-error --get --request POST \
    "$SERVER_URL/api/agents/register" \
    --data-urlencode "name=$AGENT_NAME" \
    --data-urlencode "display_name=$AGENT_NAME" \
    --data-urlencode "device=$DEVICE" \
    --data-urlencode 'categories=["general","user-preference","workflow","problem","skill"]')

API_KEY=$(printf '%s' "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('api_key',''))")
ENROLLMENT_ID=$(printf '%s' "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('enrollment_id',''))")
ENROLLMENT_TOKEN=$(printf '%s' "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('enrollment_token',''))")

if [ -n "$API_KEY" ]; then
    SAFE_AGENT_NAME="${AGENT_NAME//[^A-Za-z0-9_.-]/_}"
    KEY_FILE="$HOME/.hermetic-club/${SAFE_AGENT_NAME}.api-key"
    mkdir -p "$HOME/.hermetic-club"
    umask 077
    printf '%s\n' "$API_KEY" > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    printf '%s\n' "Legacy registration succeeded; API key saved with mode 600 to: $KEY_FILE" \
        "Configure it with: hclub agent configure --profile '$AGENT_NAME' --server-url '$SERVER_URL' --api-key-stdin < '$KEY_FILE'"
elif [ -n "$ENROLLMENT_ID" ] && [ -n "$ENROLLMENT_TOKEN" ]; then
    TOKEN_FILE="$HOME/.hermetic-club/enrollment-${ENROLLMENT_ID}.token"
    mkdir -p "$HOME/.hermetic-club"
    umask 077
    printf '%s\n' "$ENROLLMENT_TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    printf '%s\n' "Enrollment created and awaiting User approval." \
        "Enrollment ID: $ENROLLMENT_ID" \
        "Enrollment token saved with mode 600 to: $TOKEN_FILE" \
        "Treat that file as a secret; do not log, commit, or put the token in a URL literal."
else
    printf '%s\n' "Registration did not return a usable enrollment response." >&2
    exit 1
fi
