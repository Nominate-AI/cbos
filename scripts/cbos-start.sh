#!/bin/bash
# CBOS startup script - launches TypeScript server and TUI

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TS_DIR="$PROJECT_DIR/ts/packages"

API_HOST="${CBOS_API_HOST:-127.0.0.1}"
API_PORT="${CBOS_API_PORT:-32205}"
SERVER_PID=""

cleanup() {
    if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "Stopping server (PID: $SERVER_PID)..."
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}

trap cleanup EXIT

# Check if server is already running (check if port is in use)
if ss -tln | grep -q ":${API_PORT} "; then
    echo "Server already running on ${API_HOST}:${API_PORT}"
else
    echo "Starting server on ${API_HOST}:${API_PORT}..."
    cd "$TS_DIR/cbos-server"
    npm run start > /tmp/cbos-server.log 2>&1 &
    SERVER_PID=$!
    echo "Server logs: /tmp/cbos-server.log"

    # Wait for server to be ready (check port)
    for i in {1..30}; do
        if ss -tln | grep -q ":${API_PORT} "; then
            echo "Server ready"
            break
        fi
        sleep 0.2
    done
fi

# Start TUI
echo "Starting CBOS TUI..."
cd "$TS_DIR/cbos-tui"
npm run start

echo "CBOS shutdown complete"
