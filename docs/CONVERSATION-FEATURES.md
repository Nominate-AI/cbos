# Claude Code Conversation Features

This document describes the structure of Claude Code's conversation logs stored in `~/.claude/` and how to extract them for training data generation.

## Directory Structure

```
~/.claude/
├── projects/                    # Primary conversation logs (JSONL per project)
│   ├── -home-user-project-a/
│   │   ├── <session-uuid>.jsonl # Main conversation threads
│   │   ├── agent-<id>.jsonl     # Subagent/Task logs
│   │   └── <uuid>/              # Session subdirectories (plans, etc.)
│   └── -home-user-project-b/
├── history.jsonl                # User input history (prompts only)
├── debug/                       # Debug logs (timestamps, errors, LSP events)
├── todos/                       # Session todo lists
├── plans/                       # Planning mode artifacts
├── session-env/                 # Session environment snapshots
├── file-history/                # File edit history
├── __store.db                   # SQLite database (additional metadata)
└── settings.json                # User settings
```

## JSONL Message Types

Each line in a project's JSONL file is a JSON object with a `type` field:

### `type: "user"` - User Messages

```json
{
  "type": "user",
  "parentUuid": null,
  "uuid": "59aa974c-9d31-4f6e-a557-28cec9d76aae",
  "sessionId": "81adc7f6-f9aa-4c3d-8b25-bfe26e9dfd02",
  "timestamp": "2026-01-08T20:16:04.050Z",
  "cwd": "/home/user/projects/myapp",
  "userType": "external",
  "isSidechain": false,
  "message": {
    "role": "user",
    "content": "Can you help me fix this bug?"
  },
  "thinkingMetadata": {
    "level": "high",
    "disabled": false,
    "triggers": [{"start": 8, "end": 18, "text": "ultrathink"}]
  },
  "todos": []
}
```

| Field | Description |
|-------|-------------|
| `uuid` | Unique message identifier |
| `parentUuid` | Links to previous message (conversation threading) |
| `sessionId` | Session identifier (groups messages) |
| `cwd` | Working directory when message was sent |
| `isSidechain` | `true` if message is in a branched conversation |
| `thinkingMetadata` | Extended thinking triggers (ultrathink, megathink, etc.) |

### `type: "assistant"` - Assistant Responses

```json
{
  "type": "assistant",
  "parentUuid": "59aa974c-9d31-4f6e-a557-28cec9d76aae",
  "uuid": "e6f27af8-21bd-467f-8af1-d0d1a67cb5a9",
  "sessionId": "81adc7f6-f9aa-4c3d-8b25-bfe26e9dfd02",
  "timestamp": "2026-01-08T20:16:09.634Z",
  "requestId": "req_011CWvXT4MU98Vms9qEQtimT",
  "message": {
    "model": "claude-opus-4-5-20251101",
    "id": "msg_01Miof2hsFjpDwyyDSJaoEVf",
    "role": "assistant",
    "content": [
      {"type": "thinking", "thinking": "Let me analyze this bug..."},
      {"type": "text", "text": "I'll investigate the issue."},
      {"type": "tool_use", "id": "toolu_013...", "name": "Read", "input": {"file_path": "/path/to/file"}}
    ],
    "usage": {
      "input_tokens": 10,
      "output_tokens": 6,
      "cache_read_input_tokens": 12942
    }
  }
}
```

#### Content Block Types

| Block Type | Description |
|------------|-------------|
| `thinking` | Claude's extended thinking/reasoning (when triggered) |
| `text` | Regular text response |
| `tool_use` | Tool invocation (Bash, Read, Edit, Write, Grep, etc.) |

### `type: "summary"` - Session Summaries

```json
{
  "type": "summary",
  "summary": "Fix authentication bug in login flow",
  "leafUuid": "c232ccac-d870-4f2b-896d-85b67105f2ac"
}
```

Auto-generated summaries that describe the conversation topic.

### `type: "file-history-snapshot"` - File State

```json
{
  "type": "file-history-snapshot",
  "messageId": "59aa974c-9d31-4f6e-a557-28cec9d76aae",
  "snapshot": {
    "trackedFileBackups": {},
    "timestamp": "2026-01-08T20:16:04.054Z"
  }
}
```

Tracks file states for undo/restore functionality.

## Tool Use Reference

Common tools found in `tool_use` blocks:

| Tool | Description |
|------|-------------|
| `Read` | Read file contents |
| `Write` | Create/overwrite files |
| `Edit` | Edit existing files (find/replace) |
| `Bash` | Execute shell commands |
| `Grep` | Search file contents |
| `Glob` | Find files by pattern |
| `Task` | Launch subagent for complex tasks |
| `WebFetch` | Fetch and process web content |
| `WebSearch` | Search the web |
| `TodoWrite` | Manage task lists |
| `AskUserQuestion` | Ask user for clarification |

## Extraction Script

Use `scripts/extract_conversations.py` to extract training data:

### Basic Usage

```bash
# View statistics about your conversation data
python scripts/extract_conversations.py --stats

# Extract all messages to JSONL
python scripts/extract_conversations.py -o training_data.jsonl

# Extract conversation pairs (user prompt + assistant response)
python scripts/extract_conversations.py -f pairs -o pairs.jsonl

# Export in ShareGPT format for fine-tuning
python scripts/extract_conversations.py -f sharegpt -o sharegpt.jsonl
```

### Filtering Options

```bash
# Filter by project name
python scripts/extract_conversations.py -p cbos -o cbos_only.jsonl

# Filter by date range
python scripts/extract_conversations.py --after 2025-01-01 --before 2025-02-01

# Include Claude's thinking blocks (extended reasoning)
python scripts/extract_conversations.py --include-thinking -o with_thinking.jsonl

# Include branched/sidechain conversations
python scripts/extract_conversations.py --include-sidechains
```

### Output Formats

| Format | Description | Use Case |
|--------|-------------|----------|
| `jsonl` | One message per line | Raw data analysis |
| `pairs` | User/assistant pairs | Supervised fine-tuning |
| `conversations` | Full threaded conversations | Context-aware training |
| `sharegpt` | ShareGPT format | Compatible with training frameworks |

### Example Output

**Pairs Format:**
```json
{
  "user_message": "How do I implement authentication?",
  "assistant_response": "I'll help you implement authentication...",
  "thinking": "Let me analyze the current auth setup...",
  "tool_uses": [{"tool_name": "Grep", "input_data": {"pattern": "auth"}}],
  "project": "home/user/myapp",
  "session_id": "abc123",
  "timestamp": "2025-01-08T20:16:04.050Z"
}
```

**ShareGPT Format:**
```json
{
  "conversations": [
    {"from": "human", "value": "How do I implement authentication?"},
    {"from": "gpt", "value": "I'll help you implement authentication..."}
  ],
  "source": "claude-code:home/user/myapp",
  "metadata": {
    "session_id": "abc123",
    "has_thinking": true,
    "tool_count": 3
  }
}
```

## Training Data Considerations

### Quality Signals

- **Thinking blocks**: Higher quality reasoning, good for chain-of-thought training
- **Tool uses**: Demonstrates agentic behavior patterns
- **Session summaries**: Useful for task classification
- **Project context**: Group by domain for specialized models

### Filtering Recommendations

1. **Exclude sidechains** - These are abandoned conversation branches
2. **Include thinking** - Valuable for reasoning capabilities
3. **Filter by project** - Create domain-specific datasets
4. **Date filtering** - Use recent data for current patterns

### Privacy Notes

- Conversation logs may contain sensitive code and paths
- Review extracted data before sharing
- Consider anonymizing project paths and personal identifiers

## Related Files

- `history.jsonl` - Simple input history (prompts only, no responses)
- `debug/*.txt` - Debug logs with timestamps, errors, performance data
- `__store.db` - SQLite database (can query with standard tools)

## Statistics Example

```
$ python scripts/extract_conversations.py --stats -v

=== Claude Code Conversation Statistics ===

Total Messages: 45,231
  User:      12,847
  Assistant: 32,384
  With Thinking: 2,156

Projects: 134
  home/user/projects/myapp: 8,432
  home/user/projects/api: 5,221
  ...

Tool Uses: 89,432
  Read: 23,456
  Bash: 18,234
  Edit: 15,678
  Grep: 12,345
  ...

Date Range: 2024-12-01 to 2025-01-08
```
