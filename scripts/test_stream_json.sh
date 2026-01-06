#!/usr/bin/env bash
#
# Test Claude Code's stream-json output format.
# Run this on your system to verify the JSON event structure.
#
# Usage:
#   ./test_stream_json.sh
#   ./test_stream_json.sh "your custom prompt"

set -e

PROMPT="${1:-List the files in the current directory}"

echo "=== Testing Claude Code stream-json output ==="
echo "Prompt: $PROMPT"
echo "=============================================="
echo ""

# Run Claude with stream-json output
claude -p "$PROMPT" \
    --output-format stream-json \
    --dangerously-skip-permissions \
    2>&1 | while read -r line; do
    
    # Pretty-print each JSON line
    if echo "$line" | jq . 2>/dev/null; then
        # Successfully parsed as JSON
        :
    else
        # Not valid JSON, print raw
        echo "RAW: $line"
    fi
    echo "---"
done

echo ""
echo "=== Test complete ==="
