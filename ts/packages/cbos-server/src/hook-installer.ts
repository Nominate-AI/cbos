import { existsSync, mkdirSync, writeFileSync, readFileSync, chmodSync } from 'fs';
import { join, dirname } from 'path';
import { homedir } from 'os';

const HOOK_SCRIPT = `#!/usr/bin/env bash
# CBOS Input Detector Hook
# Triggered by Claude Code's Stop hook when claude finishes a turn

set -euo pipefail

CBOS_DIR="\${CBOS_DIR:-$HOME/.claude/cbos}"
EVENT_LOG="$CBOS_DIR/events.jsonl"

mkdir -p "$CBOS_DIR"

# Read hook input from stdin
HOOK_INPUT=$(cat)

# Extract stop_reason
STOP_REASON=$(echo "$HOOK_INPUT" | jq -r '.stop_reason // "unknown"')

# Only process end_turn events (Claude waiting for input)
if [[ "$STOP_REASON" != "end_turn" ]]; then
    exit 0
fi

# Extract session info
TRANSCRIPT_PATH=$(echo "$HOOK_INPUT" | jq -r '.transcript_path // empty')
SESSION_ID=$(basename "\${TRANSCRIPT_PATH%.jsonl}" 2>/dev/null || echo "unknown")

# Try to extract last assistant message from transcript
PRECEDING_TEXT=""
if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
    # Get last assistant message
    PRECEDING_TEXT=$(tac "$TRANSCRIPT_PATH" 2>/dev/null | \\
        grep -m1 '"role":"assistant"' | \\
        jq -r '.message.content | if type == "array" then map(select(.type == "text").text) | join("\\n") else . // "" end' 2>/dev/null || echo "")
fi

# Generate event
TIMESTAMP=$(date -Iseconds)
EVENT_ID=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "$$-$RANDOM")

# Write event to log
jq -nc \\
    --arg id "$EVENT_ID" \\
    --arg ts "$TIMESTAMP" \\
    --arg session "$SESSION_ID" \\
    --arg transcript "$TRANSCRIPT_PATH" \\
    --arg preceding "$PRECEDING_TEXT" \\
    '{
        event: "waiting_for_input",
        id: $id,
        timestamp: $ts,
        session: {
            id: $session,
            transcript_path: $transcript
        },
        context: {
            preceding_text: $preceding,
            text_preview: ($preceding | .[:200])
        }
    }' >> "$EVENT_LOG"

exit 0
`;

export function installHook(): { installed: boolean; hookPath: string; message: string } {
  const claudeDir = join(homedir(), '.claude');
  const hooksDir = join(claudeDir, 'hooks');
  const hookPath = join(hooksDir, 'cbos-input-detector.sh');
  const settingsPath = join(claudeDir, 'settings.json');

  // Create hooks directory
  if (!existsSync(hooksDir)) {
    mkdirSync(hooksDir, { recursive: true });
  }

  // Write hook script
  writeFileSync(hookPath, HOOK_SCRIPT);
  chmodSync(hookPath, 0o755);

  // Update settings.json to register hook
  let settings: Record<string, unknown> = {};
  if (existsSync(settingsPath)) {
    try {
      settings = JSON.parse(readFileSync(settingsPath, 'utf-8'));
    } catch {
      // Start fresh if corrupted
    }
  }

  // Ensure hooks structure exists
  if (!settings.hooks || typeof settings.hooks !== 'object') {
    settings.hooks = {};
  }

  const hooks = settings.hooks as Record<string, unknown[]>;
  if (!Array.isArray(hooks.Stop)) {
    hooks.Stop = [];
  }

  // Check if already registered
  const hookEntry = {
    matcher: '*',
    command: ['bash', hookPath],
  };

  const exists = hooks.Stop.some((h: unknown) => {
    if (typeof h === 'object' && h !== null) {
      const entry = h as Record<string, unknown>;
      if (Array.isArray(entry.command)) {
        return entry.command.includes(hookPath);
      }
    }
    return false;
  });

  if (!exists) {
    hooks.Stop.push(hookEntry);
    writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
    return {
      installed: true,
      hookPath,
      message: `Hook installed at ${hookPath} and registered in settings.json`,
    };
  }

  return {
    installed: false,
    hookPath,
    message: `Hook already registered at ${hookPath}`,
  };
}

export function getHookPath(): string {
  return join(homedir(), '.claude', 'hooks', 'cbos-input-detector.sh');
}
