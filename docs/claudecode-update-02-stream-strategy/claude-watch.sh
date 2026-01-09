#!/usr/bin/env bash
# claude-watch.sh - Watch Claude Code sessions for "waiting for input" states
# Detects when Claude has finished responding and is awaiting user input

CLAUDE_PROJECTS="${CLAUDE_PROJECTS:-$HOME/.claude/projects}"
OUTPUT_FORMAT="${OUTPUT_FORMAT:-pretty}"  # pretty, json, or minimal

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Track state per session
declare -A LAST_ROLE
declare -A LAST_CONTENT

emit_waiting() {
    local session="$1"
    local content="$2"
    local timestamp=$(date -Iseconds)
    
    case "$OUTPUT_FORMAT" in
        json)
            jq -nc --arg s "$session" --arg c "$content" --arg t "$timestamp" \
                '{event:"waiting_for_input", session:$s, timestamp:$t, preceding_text:$c}'
            ;;
        minimal)
            echo ">>> WAITING: $session"
            ;;
        pretty|*)
            echo -e "\n${GREEN}━━━ WAITING FOR INPUT ━━━${NC}"
            echo -e "${CYAN}Session:${NC} $(basename "$session" .jsonl)"
            echo -e "${CYAN}Time:${NC} $timestamp"
            echo -e "${YELLOW}Preceding:${NC}"
            echo "$content" | head -c 2000
            echo -e "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
            ;;
    esac
}

process_line() {
    local file="$1"
    local line="$2"
    
    # Skip non-JSON lines
    [[ "$line" != "{"* ]] && return
    
    # Parse the message
    local parsed
    parsed=$(echo "$line" | jq -c '{
        type: .type,
        role: .message.role // .role,
        content: (
            if .message.content then
                (.message.content | if type == "array" then 
                    map(select(.type == "text").text) | join("\n")
                else . end)
            elif .content then
                (.content | if type == "array" then
                    map(select(.type == "text").text) | join("\n")
                else . end)
            else null end
        ),
        stop_reason: .message.stop_reason // .stop_reason,
        is_tool_use: (.message.content // .content | if type == "array" then
            any(.[]; .type == "tool_use")
        else false end)
    }' 2>/dev/null) || return
    
    local role=$(echo "$parsed" | jq -r '.role // empty')
    local content=$(echo "$parsed" | jq -r '.content // empty')
    local stop_reason=$(echo "$parsed" | jq -r '.stop_reason // empty')
    local is_tool_use=$(echo "$parsed" | jq -r '.is_tool_use')
    
    # Track assistant messages
    if [[ "$role" == "assistant" ]]; then
        LAST_ROLE["$file"]="assistant"
        [[ -n "$content" ]] && LAST_CONTENT["$file"]="$content"
        
        # Check if this is end_turn (waiting for user) vs tool_use (will continue)
        if [[ "$stop_reason" == "end_turn" && "$is_tool_use" != "true" ]]; then
            emit_waiting "$file" "${LAST_CONTENT[$file]}"
        fi
    elif [[ "$role" == "user" ]]; then
        LAST_ROLE["$file"]="user"
    fi
}

watch_with_fswatch() {
    echo -e "${BLUE}Watching with fswatch...${NC}" >&2
    
    # Initial tail of recent content
    for f in "$CLAUDE_PROJECTS"/*/*.jsonl; do
        [[ -f "$f" ]] && tail -n 5 "$f" 2>/dev/null | while read -r line; do
            process_line "$f" "$line"
        done
    done
    
    # Watch for changes
    fswatch -0 --event Updated "$CLAUDE_PROJECTS" 2>/dev/null | while IFS= read -r -d '' file; do
        [[ "$file" == *.jsonl ]] || continue
        # Get the last line (new content)
        tail -n 1 "$file" 2>/dev/null | while read -r line; do
            process_line "$file" "$line"
        done
    done
}

watch_with_inotifywait() {
    echo -e "${BLUE}Watching with inotifywait...${NC}" >&2
    
    # Initial tail
    for f in "$CLAUDE_PROJECTS"/*/*.jsonl; do
        [[ -f "$f" ]] && tail -n 5 "$f" 2>/dev/null | while read -r line; do
            process_line "$f" "$line"
        done
    done
    
    # Watch for modifications
    inotifywait -m -q -e modify --format '%w%f' -r "$CLAUDE_PROJECTS" 2>/dev/null | while read -r file; do
        [[ "$file" == *.jsonl ]] || continue
        tail -n 1 "$file" 2>/dev/null | while read -r line; do
            process_line "$file" "$line"
        done
    done
}

watch_with_tail() {
    echo -e "${BLUE}Falling back to tail -F...${NC}" >&2
    
    # Less reliable but works everywhere
    tail -F "$CLAUDE_PROJECTS"/*/*.jsonl 2>/dev/null | while read -r line; do
        # Can't easily get filename with tail -F on multiple files
        # This is why fswatch/inotifywait is preferred
        process_line "unknown" "$line"
    done
}

# Main
echo -e "${CYAN}Claude Code Input Watcher${NC}" >&2
echo -e "Watching: $CLAUDE_PROJECTS" >&2
echo -e "Format: $OUTPUT_FORMAT (set OUTPUT_FORMAT=json|pretty|minimal)" >&2
echo "" >&2

if command -v fswatch &>/dev/null; then
    watch_with_fswatch
elif command -v inotifywait &>/dev/null; then
    watch_with_inotifywait
else
    echo -e "${YELLOW}Warning: Neither fswatch nor inotifywait found${NC}" >&2
    echo -e "Install with: brew install fswatch (macOS) or apt install inotify-tools (Linux)" >&2
    watch_with_tail
fi
