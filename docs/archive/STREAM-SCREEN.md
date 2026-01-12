# Streaming from 'screen’

**1. Using `script` inside screen (best for new sessions)**

```bash
# Launch screen with script capturing everything
screen -dmS claude1 script -f /tmp/claude1.typescript -c 'claude'

# -f flushes after each write (real-time capture)
```

This captures the full I/O stream including timing.

**2. Replay with timing data**

```bash
# Record with timing
screen -dmS claude1 script -f --timing=/tmp/claude1.timing /tmp/claude1.typescript -c 'claude'

# Replay at original speed
scriptreplay /tmp/claude1.timing /tmp/claude1.typescript
```

**3. Capture stdout/stderr separately**

```bash
screen -dmS claude1 bash -c 'claude > /tmp/claude1.stdout 2> /tmp/claude1.stderr'

# Or combined but labeled
screen -dmS claude1 bash -c 'claude > /tmp/claude1.out 2>&1'
```

**4. Using `tee` for live output + capture**

```bash
screen -dmS claude1 bash -c 'claude 2>&1 | tee /tmp/claude1.log'
```

**5. Attach to streams of an already-running process with `strace`**

```bash
# Find the PID of the process inside screen
pgrep -f claude

# Capture its file descriptor I/O
strace -p PID -e read,write -s 1000 -o /tmp/io_capture.txt

# Just stdout (fd 1) and stderr (fd 2)
strace -p PID -e write -s 1000 2>&1 | grep -E '^write\([12],'
```

**6. Using `reptyr` to steal a process to a new terminal**

```bash
# Move an existing process to current terminal (for debugging)
reptyr PID
```

**7. Tap into `/proc` file descriptors (read-only peek)**

```bash
# See what file descriptors a process has open
ls -la /proc/PID/fd/

# These are symlinks - you can sometimes tail them
# fd/0 = stdin, fd/1 = stdout, fd/2 = stderr
```

**8. Named pipes for interception (advanced, requires planning)**

```bash
# Create pipes
mkfifo /tmp/claude_in /tmp/claude_out

# Launch with redirection through pipes
screen -dmS claude1 bash -c 'claude < /tmp/claude_in > /tmp/claude_out 2>&1'

# Tap the output
cat /tmp/claude_out | tee /tmp/captured.log
```

-----

**Practical recommendation for your use case:**

Wrap Claude Code launches with `script`:

```bash
#!/bin/bash
name="$1"
dir="$2"
logdir="$HOME/claude_streams"
mkdir -p "$logdir"

screen -dmS "$name" script -f \
    --timing="$logdir/${name}.timing" \
    "$logdir/${name}.typescript" \
    -c "cd '$dir' && NO_COLOR=1 claude"
```

This gives you:

- Full I/O capture (not just buffer snapshots)
- Real-time flushing with `-f`
- Ability to replay sessions exactly as they happened
- Works cleanly with screen’s session management

Want me to add this to the guide?​​​​​​​​​​​​​​​​