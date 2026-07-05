#!/usr/bin/env bash
# One-shot agent registration with Hermetic Club
# Usage: ./register.sh <server-url> <agent-name>

set -euo pipefail

SERVER_URL="${1:-http://100.x.x.x:8765}"
AGENT_NAME="${2:-}"
DEVICE="${3:-$(hostname)}"

if [ -z "$AGENT_NAME" ]; then
    echo "Usage: $0 <server-url> <agent-name> [device]"
    echo ""
    echo "Example:"
    echo "  $0 http://100.64.1.2:8765 arch-desktop"
    exit 1
fi

echo "✦ Registering agent '$AGENT_NAME' with Hermetic Club at $SERVER_URL..."

RESPONSE=$(curl -s -X POST "$SERVER_URL/api/agents/register" \
    -d "name=$AGENT_NAME" \
    -d "display_name=$AGENT_NAME" \
    -d "device=$DEVICE" \
    -d "categories=[\"general\",\"user-preference\",\"workflow\",\"problem\",\"skill\"]")

echo ""
echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
echo ""

API_KEY=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('api_key',''))" 2>/dev/null || true)

if [ -n "$API_KEY" ]; then
    echo "⚠ SAVE THIS API KEY — it won't be shown again."
    echo ""
    echo "Add it to ~/.hermetic-club/agent-config.yaml:"
    echo ""
    echo "  club_url: \"$SERVER_URL\""
    echo "  agent_name: \"$AGENT_NAME\""
    echo "  api_key: \"$API_KEY\""
fi
