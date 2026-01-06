#!/bin/bash
set -e

cd /home/bisenbek/projects/nominate/cbos

# Kill any existing cbos processes
echo "Stopping old processes..."
pkill -f "cbos-server" 2>/dev/null || true
pkill -f "cbos-tui" 2>/dev/null || true
# Also kill any node processes on port 32205
fuser -k 32205/tcp 2>/dev/null || true
sleep 1

# Build
echo "Building server..."
cd ts/packages/cbos-server && npm run build

echo "Building TUI..."
cd ../cbos-tui && npm run build

# Run
echo "Starting CBOS..."
cd /home/bisenbek/projects/nominate/cbos
./scripts/cbos-start.sh
