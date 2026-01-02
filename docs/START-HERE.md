# Managing Claude Code Sessions with GNU Screen

A practical guide to running, monitoring, and capturing output from headless Claude Code sessions.

---

## Launching Headless Sessions

### Basic Syntax

```bash
# Start detached screen running a command
screen -dmS session_name command arg1 arg2

# Example with Claude Code
screen -dmS claude1 claude --resume

# With a specific working directory
screen -dmS mywork bash -c 'cd /project && claude'
```

### Useful Flags

| Flag | Purpose |
|------|---------|
| `-d` | Detached (don't attach) |
| `-m` | Force new session even if one exists |
| `-S` | Name the session |
| `-L` | Enable logging from start |
| `-Logfile` | Specify log path (newer screen versions) |

### With Logging Enabled from Start

```bash
screen -dmS claude1 -L -Logfile /tmp/claude1.log claude --resume
```

### Launching Multiple Sessions

```bash
#!/bin/bash
PROJECTS=(
    "project1:/home/user/project1"
    "project2:/home/user/project2"
    "project3:/home/user/project3"
)

for entry in "${PROJECTS[@]}"; do
    name="${entry%%:*}"
    path="${entry#*:}"
    screen -dmS "$name" bash -c "cd '$path' && claude"
done
```

### With Staggered Startup Delay

```bash
screen -dmS claude1 bash -c 'sleep 5 && claude --resume'
```

### Verify Running Sessions

```bash
screen -ls
```

### Send Commands to Running Session

```bash
# Send keystrokes to a detached session
screen -S session_name -X stuff 'some command\n'
```

---

## Capturing Screen Buffers

### Snapshot Methods

```bash
# Capture visible screen only
screen -S session_name -X hardcopy /tmp/session_name.txt

# Capture entire scrollback buffer (recommended)
screen -S session_name -X hardcopy -h /tmp/session_name.txt
```

> **Note:** The `-h` flag is essential for capturing the full scrollback history, not just the visible portion.

### Enable Logging on Running Sessions

```bash
# Turn on logging for an existing session
screen -S session_name -X logfile /tmp/session_name.log
screen -S session_name -X log on
```

Output will continuously append to the logfile from that point forward.

### Increase Scrollback Buffer

Add to `~/.screenrc` for all future sessions:

```
defscrollback 10000
```

Or modify a running session:

```bash
screen -S session_name -X scrollback 10000
```

### Periodic Capture Script

```bash
#!/bin/bash
# capture_screens.sh - Capture all screen session buffers

OUTDIR="$HOME/screen_captures/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTDIR"

screen -ls | grep -oP '\d+\.\S+' | while read session; do
    safe_name="${session//\//_}"
    screen -S "$session" -X hardcopy -h "$OUTDIR/${safe_name}.txt"
done
```

Add to cron for automated captures:

```bash
# Every 15 minutes
*/15 * * * * /path/to/capture_screens.sh
```

---

## Handling ANSI Color Codes

Claude Code outputs ANSI escape sequences for colors, which appear as garbage characters (`?` or `^[[0m`) in log files.

### Prevention: Disable Colors at Launch

```bash
# Using NO_COLOR standard
NO_COLOR=1 claude

# Force dumb terminal
TERM=dumb claude

# Combined in a screen launch
screen -dmS claude1 bash -c 'NO_COLOR=1 claude --resume'
```

### Check Claude Code's Native Options

```bash
claude --help
```

Look for `--no-color`, `--plain`, or similar flags.

### Post-Processing: Strip ANSI Codes

If colors can't be disabled, clean the output after capture:

```bash
# Using sed
sed 's/\x1b\[[0-9;]*m//g' logfile.txt > clean.txt

# Using perl (handles more escape sequences)
perl -pe 's/\e\[[0-9;]*m//g' logfile.txt > clean.txt

# Using ansi2txt (from colorized-logs package)
# Install: apt install colorized-logs
ansi2txt < logfile.txt > clean.txt
```

### Comprehensive ANSI Stripping

For stubborn escape sequences, use a more aggressive pattern:

```bash
# Strips all common ANSI escape sequences
sed 's/\x1b\[[0-9;]*[a-zA-Z]//g' logfile.txt > clean.txt
```

---

## Complete Workflow Script

A unified script for launching, logging, and capturing Claude Code sessions:

```bash
#!/bin/bash
# claude-screen-manager.sh

LOGDIR="$HOME/claude_logs"
CAPTUREDIR="$HOME/claude_captures"

mkdir -p "$LOGDIR" "$CAPTUREDIR"

usage() {
    echo "Usage: $0 {launch|capture|clean|list}"
    echo ""
    echo "Commands:"
    echo "  launch NAME DIR    Launch Claude Code in screen session"
    echo "  capture            Capture all screen buffers"
    echo "  clean FILE         Strip ANSI codes from file"
    echo "  list               List running screen sessions"
    exit 1
}

launch_session() {
    local name="$1"
    local dir="$2"
    
    if [[ -z "$name" || -z "$dir" ]]; then
        echo "Usage: $0 launch NAME DIRECTORY"
        exit 1
    fi
    
    local logfile="$LOGDIR/${name}.log"
    
    screen -dmS "$name" -L -Logfile "$logfile" \
        bash -c "cd '$dir' && NO_COLOR=1 claude"
    
    echo "Launched session '$name' in $dir"
    echo "Log file: $logfile"
}

capture_all() {
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local outdir="$CAPTUREDIR/$timestamp"
    mkdir -p "$outdir"
    
    screen -ls | grep -oP '\d+\.\S+' | while read session; do
        safe_name="${session//\//_}"
        local outfile="$outdir/${safe_name}.txt"
        screen -S "$session" -X hardcopy -h "$outfile"
        
        # Auto-clean ANSI codes
        sed -i 's/\x1b\[[0-9;]*[a-zA-Z]//g' "$outfile"
        
        echo "Captured: $outfile"
    done
}

clean_file() {
    local file="$1"
    if [[ -z "$file" ]]; then
        echo "Usage: $0 clean FILENAME"
        exit 1
    fi
    
    sed -i 's/\x1b\[[0-9;]*[a-zA-Z]//g' "$file"
    echo "Cleaned: $file"
}

list_sessions() {
    screen -ls
}

case "$1" in
    launch)  launch_session "$2" "$3" ;;
    capture) capture_all ;;
    clean)   clean_file "$2" ;;
    list)    list_sessions ;;
    *)       usage ;;
esac
```

### Usage Examples

```bash
# Make executable
chmod +x claude-screen-manager.sh

# Launch a new session
./claude-screen-manager.sh launch myproject /home/user/myproject

# List running sessions
./claude-screen-manager.sh list

# Capture all sessions (with auto ANSI cleaning)
./claude-screen-manager.sh capture

# Clean a specific file
./claude-screen-manager.sh clean /tmp/messy_log.txt
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Launch headless | `screen -dmS name claude` |
| Attach to session | `screen -r name` |
| Detach from session | `Ctrl+A, D` |
| List sessions | `screen -ls` |
| Kill session | `screen -S name -X quit` |
| Capture buffer | `screen -S name -X hardcopy -h /path/file.txt` |
| Enable logging | `screen -S name -X log on` |
| Send keystrokes | `screen -S name -X stuff 'text\n'` |
| Strip ANSI | `sed 's/\x1b\[[0-9;]*[a-zA-Z]//g' file` |

---

## Recommended ~/.screenrc

```
# Increase scrollback buffer
defscrollback 50000

# Enable logging by default
deflog on
logfile $HOME/screen_logs/screenlog.%S.%n

# Status line
hardstatus alwayslastline
hardstatus string '%{= kG}[ %{G}%H %{g}][%= %{= kw}%?%-Lw%?%{r}(%{W}%n*%f%t%?(%u)%?%{r})%{w}%?%+Lw%?%?%= %{g}][%{B} %m-%d %{W}%c %{g}]'

# Disable startup message
startup_message off

# UTF-8
defutf8 on
```

Create the log directory:

```bash
mkdir -p ~/screen_logs
```
