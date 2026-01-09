#!/usr/bin/env bash
# claude-input-hook.sh - Hook to detect when Claude Code is waiting for user input
#
# SETUP:
# 1. Save this file somewhere (e.g., ~/.claude/hooks/input-hook.sh)
# 2. Make executable: chmod +x ~/.claude/hooks/input-hook.sh
# 3. Add to ~/.claude/settings.json:
#
#    {
#      "hooks": {
#        "PostToolUse": [
#          {
#            "matcher": "*",
#            "command": ["~/.claude/hooks/input-hook.sh", "post-tool"]
#          }
#        ],
#        "NotificationHook": [
#          {
#            "matcher": "*", 
#            "command": ["~/.claude/hooks/input-hook.sh", "notification"]
#          }
#        ],
#        "Stop": [
#          {
#            "matcher": "*",
#            "command": ["~/.claude/hooks/input-hook.sh", "stop"]
#          }
#        ]
#      }
#    }
#
# Or use /hooks in Claude Code TUI to configure interactively.

set -euo pipefail

HOOK_TYPE="${1:-unknown}"
LOG_FILE="${CLAUDE_HOOK_LOG:-$HOME/.claude/input-events.jsonl}"
NOTIFY="${CLAUDE_HOOK_NOTIFY:-false}"  # Set to "true" to get desktop notifications

# Read hook input from stdin (Claude passes JSON via stdin)
INPUT=$(cat)

log_event() {
    local event_type="$1"
    local data="$2"
    
    jq -nc \
        --arg type "$event_type" \
        --arg ts "$(date -Iseconds)" \
        --argjson data "$data" \
        '{event_type: $type, timestamp: $ts, data: $data}' >> "$LOG_FILE"
}

notify_user() {
    local title="$1"
    local message="$2"
    
    [[ "$NOTIFY" != "true" ]] && return
    
    if command -v osascript &>/dev/null; then
        # macOS
        osascript -e "display notification \"$message\" with title \"$title\""
    elif command -v notify-send &>/dev/null; then
        # Linux
        notify-send "$title" "$message"
    fi
}

case "$HOOK_TYPE" in
    stop)
        # This fires when Claude stops - key event for "waiting for input"
        stop_reason=$(echo "$INPUT" | jq -r '.stop_reason // "unknown"')
        
        if [[ "$stop_reason" == "end_turn" ]]; then
            # Claude finished and is waiting for user input
            # Extract the transcript path to get preceding context
            transcript=$(echo "$INPUT" | jq -r '.transcript_path // empty')
            
            # Get last assistant message from transcript
            preceding=""
            if [[ -n "$transcript" && -f "$transcript" ]]; then
                preceding=$(tac "$transcript" | grep -m1 '"role":"assistant"' | \
                    jq -r '.message.content | if type == "array" then 
                        map(select(.type == "text").text) | join("\n") 
                    else . end' 2>/dev/null || echo "")
            fi
            
            log_event "waiting_for_input" "$(jq -nc \
                --arg reason "$stop_reason" \
                --arg preceding "$preceding" \
                '{stop_reason: $reason, preceding_text: $preceding}')"
            
            notify_user "Claude Code" "Waiting for your input"
            
            # Output to stderr so it shows in terminal if running interactively
            echo "[$(date +%H:%M:%S)] WAITING FOR INPUT" >&2
            [[ -n "$preceding" ]] && echo "Last response: ${preceding:0:200}..." >&2
        fi
        ;;
        
    post-tool)
        # Tool just finished - useful for tracking what Claude is doing
        tool_name=$(echo "$INPUT" | jq -r '.tool_name // "unknown"')
        tool_id=$(echo "$INPUT" | jq -r '.tool_use_id // "unknown"')
        
        log_event "tool_completed" "$(jq -nc \
            --arg tool "$tool_name" \
            --arg id "$tool_id" \
            '{tool: $tool, tool_use_id: $id}')"
        ;;
        
    notification)
        # General notifications from Claude Code
        notification=$(echo "$INPUT" | jq -r '.notification // empty')
        log_event "notification" "$(jq -nc --arg msg "$notification" '{message: $msg}')"
        ;;
        
    *)
        # Log unknown events for debugging
        log_event "unknown_$HOOK_TYPE" "$INPUT"
        ;;
esac

exit 0
