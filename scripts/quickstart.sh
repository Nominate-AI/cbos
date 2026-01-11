#!/bin/bash
#
# CBOS Quickstart - Launch or connect to a Claude Code session
#
# Usage: ./quickstart.sh <PROJECT_DIR>
#
# Features:
#   - Validates project directory
#   - Checks for existing screen session
#   - Creates new session or attaches to existing
#   - Streams debug output to stdout/stderr and journald (cb group)
#

set -euo pipefail

# Configuration
CBOS_STREAM_DIR="${CBOS_STREAM_DIR:-$HOME/claude_streams}"
CBOS_LOG_DIR="${CBOS_LOG_DIR:-$HOME/claude_logs}"
CBOS_CLAUDE_CMD="${CBOS_CLAUDE_CMD:-claude}"
CBOS_CLAUDE_ENV="${CBOS_CLAUDE_ENV:-}"
JOURNALD_TAG="cb"

# Colors (disabled if NO_COLOR is set)
if [[ -z "${NO_COLOR:-}" ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    NC='\033[0m' # No Color
else
    RED='' GREEN='' YELLOW='' BLUE='' CYAN='' NC=''
fi

log_debug() {
    local msg="[DEBUG] $*"
    echo -e "${CYAN}${msg}${NC}" >&2
    logger -t "$JOURNALD_TAG" -p user.debug "$msg" 2>/dev/null || true
}

log_info() {
    local msg="[INFO] $*"
    echo -e "${GREEN}${msg}${NC}"
    logger -t "$JOURNALD_TAG" -p user.info "$msg" 2>/dev/null || true
}

log_warn() {
    local msg="[WARN] $*"
    echo -e "${YELLOW}${msg}${NC}" >&2
    logger -t "$JOURNALD_TAG" -p user.warning "$msg" 2>/dev/null || true
}

log_error() {
    local msg="[ERROR] $*"
    echo -e "${RED}${msg}${NC}" >&2
    logger -t "$JOURNALD_TAG" -p user.err "$msg" 2>/dev/null || true
}

usage() {
    cat << EOF
Usage: $(basename "$0") <PROJECT_DIR>

Launch or connect to a Claude Code session for the specified project.

Arguments:
  PROJECT_DIR    Path to the project directory

Environment Variables:
  CBOS_STREAM_DIR    Directory for typescript streams (default: ~/claude_streams)
  CBOS_LOG_DIR       Directory for screen logs (default: ~/claude_logs)
  CBOS_CLAUDE_CMD    Claude command (default: claude)
  CBOS_CLAUDE_ENV    Extra environment variables for Claude
  NO_COLOR           Disable colored output

Examples:
  $(basename "$0") /home/user/projects/myapp
  $(basename "$0") .
  CBOS_CLAUDE_ENV="MAX_THINKING_TOKENS=32000" $(basename "$0") ~/work/api

EOF
    exit 1
}

# Derive session slug from project path
get_slug() {
    local project_dir="$1"
    # Use basename of realpath, uppercase, replace non-alphanumeric with underscore
    local slug
    slug=$(basename "$(realpath "$project_dir")" | tr '[:lower:]' '[:upper:]' | tr -c '[:alnum:]' '_' | sed 's/_*$//')
    # Truncate to 12 chars for screen compatibility
    echo "${slug:0:12}"
}

# Check if screen session exists
session_exists() {
    local slug="$1"
    screen -ls 2>/dev/null | grep -q "\.${slug}[[:space:]]"
}

# Get session info
get_session_info() {
    local slug="$1"
    screen -ls 2>/dev/null | grep "\.${slug}[[:space:]]" | head -1
}

# Create new session with streaming
create_session() {
    local slug="$1"
    local project_dir="$2"

    # Ensure directories exist
    mkdir -p "$CBOS_STREAM_DIR" "$CBOS_LOG_DIR"

    local typescript_file="$CBOS_STREAM_DIR/${slug}.typescript"
    local timing_file="$CBOS_STREAM_DIR/${slug}.timing"
    local logfile="$CBOS_LOG_DIR/${slug}.log"

    # Build environment string
    local env_vars="NO_COLOR=1"
    [[ -n "$CBOS_CLAUDE_ENV" ]] && env_vars="$env_vars $CBOS_CLAUDE_ENV"

    # Command to run inside screen: script wraps claude for streaming
    local script_cmd="script -f --timing=${timing_file} ${typescript_file} -c 'cd \"${project_dir}\" && ${env_vars} ${CBOS_CLAUDE_CMD}'"

    log_debug "Creating session: $slug"
    log_debug "Project: $project_dir"
    log_debug "Typescript: $typescript_file"
    log_debug "Command: $script_cmd"

    # Launch screen session
    screen -dmS "$slug" -L -Logfile "$logfile" bash -c "$script_cmd"

    # Wait briefly for session to start
    sleep 0.5

    if session_exists "$slug"; then
        log_info "Created new session: $slug"
        return 0
    else
        log_error "Failed to create session"
        return 1
    fi
}

# Stream typescript output in background
stream_output() {
    local slug="$1"
    local typescript_file="$CBOS_STREAM_DIR/${slug}.typescript"

    # Wait for typescript file to exist
    local wait_count=0
    while [[ ! -f "$typescript_file" ]] && [[ $wait_count -lt 20 ]]; do
        sleep 0.25
        ((wait_count++))
    done

    if [[ ! -f "$typescript_file" ]]; then
        log_warn "Typescript file not found after 5s: $typescript_file"
        return 1
    fi

    log_debug "Streaming from: $typescript_file"

    # Tail the typescript file and also send to journald
    tail -f "$typescript_file" 2>/dev/null | while IFS= read -r line; do
        echo "$line"
        # Send significant lines to journald (skip empty and very short lines)
        if [[ ${#line} -gt 10 ]]; then
            logger -t "$JOURNALD_TAG" -p user.debug "$slug: $line" 2>/dev/null || true
        fi
    done
}

# Main
main() {
    if [[ $# -lt 1 ]]; then
        usage
    fi

    local project_dir="$1"

    # Validate project directory
    log_debug "Validating project directory: $project_dir"

    # Expand path
    if [[ "$project_dir" == "." ]]; then
        project_dir="$(pwd)"
    elif [[ ! "$project_dir" =~ ^/ ]]; then
        project_dir="$(realpath "$project_dir" 2>/dev/null || echo "$PWD/$project_dir")"
    fi

    if [[ ! -d "$project_dir" ]]; then
        log_error "Not a valid directory: $project_dir"
        exit 1
    fi

    if [[ ! -r "$project_dir" ]]; then
        log_error "Directory not readable: $project_dir"
        exit 1
    fi

    log_debug "Project directory validated: $project_dir"

    # Derive session slug
    local slug
    slug=$(get_slug "$project_dir")
    log_debug "Session slug: $slug"

    # Check for existing session
    if session_exists "$slug"; then
        local session_info
        session_info=$(get_session_info "$slug")
        log_info "Found existing session: $session_info"

        # Start background streaming before attaching
        log_debug "Starting output stream..."
        stream_output "$slug" &
        local stream_pid=$!

        # Cleanup stream on exit
        trap "kill $stream_pid 2>/dev/null || true" EXIT

        log_info "Attaching to session: $slug"
        log_info "Press Ctrl+A, D to detach"
        sleep 0.5

        # Attach to existing session
        screen -r "$slug"
    else
        log_info "No existing session found for: $slug"

        # Create new session
        if ! create_session "$slug" "$project_dir"; then
            exit 1
        fi

        # Start background streaming
        log_debug "Starting output stream..."
        stream_output "$slug" &
        local stream_pid=$!

        # Cleanup stream on exit
        trap "kill $stream_pid 2>/dev/null || true" EXIT

        log_info "Attaching to new session: $slug"
        log_info "Press Ctrl+A, D to detach"
        sleep 0.5

        # Attach to the new session
        screen -r "$slug"
    fi

    log_info "Session detached: $slug"
    log_debug "To reattach: screen -r $slug"
    log_debug "To view logs: journalctl -t $JOURNALD_TAG --since '1 hour ago'"
}

main "$@"
