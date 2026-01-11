# CBOS Orchestrator Usage Guide

The CBOS Orchestrator provides pattern-based intelligence for Claude Code sessions. It extracts decision patterns from conversation history, stores them with embeddings, and can suggest or auto-answer similar questions in real-time.

## Quick Start

```bash
# Activate environment
source ~/.pyenv/versions/tinymachines/bin/activate

# Build pattern database from conversation logs
cbos-patterns build

# Watch live session events
cbos-patterns watch

# Listen with pattern matching
cbos-patterns listen
```

## Commands

### `cbos-patterns build`

Extract decision patterns from Claude Code conversation logs and generate embeddings.

```bash
# Build from all conversations
cbos-patterns build

# Filter by project
cbos-patterns build -p myproject

# Filter by date range
cbos-patterns build --after 2025-01-01 --before 2025-12-31

# Skip embedding generation (faster, but no similarity search)
cbos-patterns build --no-embeddings

# Custom batch size for embedding API calls
cbos-patterns build --batch-size 20
```

**What it does:**
1. Scans `~/.claude/projects/` for conversation JSONL files
2. Extracts `AskUserQuestion` tool calls and user responses
3. Stores patterns in SQLite (`~/.cbos/patterns.db`)
4. Generates embeddings via CBAI API (`https://ai.nominate.ai`)
5. Stores vectors in vectl (`~/.cbos/vectors.bin`)

### `cbos-patterns query`

Find similar patterns using semantic search.

```bash
# Basic query
cbos-patterns query "Which authentication method should I use?"

# Adjust similarity threshold (0-1, default: 0.7)
cbos-patterns query "Should I proceed?" --threshold 0.5

# Limit results
cbos-patterns query "How to handle errors?" --limit 5

# Filter by question type
cbos-patterns query "Database choice?" --type decision

# Filter by project
cbos-patterns query "API design?" -p myproject

# Output as JSON
cbos-patterns query "Testing strategy?" --json
```

### `cbos-patterns search`

Full-text search on question text (no embeddings required).

```bash
# Search for keyword
cbos-patterns search "authentication"

# Limit results
cbos-patterns search "database" --limit 10

# Output as JSON
cbos-patterns search "API" --json
```

### `cbos-patterns stats`

Show database statistics.

```bash
# Display stats
cbos-patterns stats

# Output as JSON
cbos-patterns stats --json
```

**Sample output:**
```
Pattern Database Statistics

Total patterns: 46
With embeddings: 46

Vector Store (vectl):
  Path: /home/user/.cbos/vectors.bin
  Dimensions: 768
  Clusters: 50
  File size: 100.0 MB
  Connected: True

Date range: 2025-12-10 to 2026-01-09

By Question Type:
  decision: 46

Top Projects:
  home/user/projects/myapp: 14
  home/user/projects/backend: 8
```

### `cbos-patterns watch`

Watch all WebSocket events from the CBOS server in real-time.

```bash
# Watch events with nice formatting
cbos-patterns watch

# Show raw JSON messages
cbos-patterns watch --raw

# Hide session state updates (quieter)
cbos-patterns watch -q

# Connect to different port
cbos-patterns watch -p 32206
```

**Event icons:**
| Icon | Category | Description |
|------|----------|-------------|
| ▶ | init | Session started |
| ◐ | thinking | Claude processing |
| 💬 | text | Text output |
| ⚙ | tool_use | Tool being called |
| ✓ | tool_result | Tool returned result |
| ● | result | Turn completed |
| ✗ | error | Error occurred |
| ⏳ | waiting | Waiting for input |
| ❓ | question | AskUserQuestion |
| 👤 | user_msg | User message |

### `cbos-patterns listen`

Listen to sessions and match patterns in real-time. When questions are detected, queries the pattern database for similar historical questions.

```bash
# Listen with pattern matching (suggestions only)
cbos-patterns listen

# Enable auto-answering for high-confidence matches
cbos-patterns listen --auto-answer

# Adjust thresholds
cbos-patterns listen --auto-threshold 0.90 --suggest-threshold 0.75

# Verbose mode (show all session updates)
cbos-patterns listen -v

# Connect to different port
cbos-patterns listen -p 32206
```

**Thresholds:**
- `--auto-threshold` (default: 0.95): Similarity score required for auto-answering
- `--suggest-threshold` (default: 0.80): Similarity score required for logging suggestions

**Sample output:**
```
Starting orchestrator listener...
Connecting to: ws://localhost:32205
Auto-answer: False
Auto-answer threshold: 95%
Suggestion threshold: 80%

Connected to CBOS server
Listening for questions... (Ctrl+C to stop)

[AUTH] Question: Which authentication method should we use?
  Options: JWT, OAuth2, Session-based
[AUTH] Suggestion (87%): Use JWT with refresh tokens
[BACKEND] Question: Should I proceed with this refactor?
[BACKEND] Auto-answered: Yes, proceed with the refactor
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    cbos-patterns CLI                            │
├─────────────────────────────────────────────────────────────────┤
│  build   │  query  │  search │  stats  │  watch  │  listen     │
└────┬─────┴────┬────┴────┬────┴────┬────┴────┬────┴────┬────────┘
     │          │         │         │         │         │
     ▼          ▼         ▼         ▼         ▼         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PatternStore                                │
│  - Pattern CRUD via SQLite                                      │
│  - Vector similarity via vectl                                  │
│  - Embedding generation via CBAI                                │
└──────────────┬──────────────────────────────────┬───────────────┘
               │                                  │
┌──────────────▼──────────────┐    ┌──────────────▼───────────────┐
│   SQLite (patterns.db)      │    │   vectl (vectors.bin)        │
│   - Pattern metadata        │    │   - 768-dim embeddings       │
│   - Question text           │    │   - K-means clustering       │
│   - User answers            │    │   - Similarity search        │
└─────────────────────────────┘    └──────────────────────────────┘
```

## Data Flow

### Pattern Extraction (build)
```
~/.claude/projects/*.jsonl
        │
        ▼
DecisionPatternExtractor
  - Parse JSONL messages
  - Find AskUserQuestion tool_use
  - Extract question + user response
        │
        ▼
CBAI API (https://ai.nominate.ai)
  - Generate 768-dim embeddings
  - nomic-embed-text model
        │
        ▼
PatternStore
  - SQLite: metadata
  - vectl: vectors
```

### Real-time Matching (listen)
```
CBOS WebSocket Server (port 32205)
        │
        │ formatted_event (category: question)
        ▼
OrchestratorListener
  - Parse question text
  - Generate query embedding
        │
        ▼
PatternStore.query_similar_text()
  - vectl K-means search
  - Return top matches
        │
        ▼
Response Handler
  - >= 95%: Auto-answer
  - >= 80%: Log suggestion
  - < 80%: No action
```

## Configuration

Environment variables (prefix: `CBOS_ORCHESTRATOR_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `CBOS_ORCHESTRATOR_PATTERN_DB_PATH` | `~/.cbos/patterns.db` | SQLite database path |
| `CBOS_ORCHESTRATOR_VECTOR_STORE_PATH` | `~/.cbos/vectors.bin` | vectl store path |
| `CBOS_ORCHESTRATOR_CBAI_URL` | `https://ai.nominate.ai` | CBAI API URL |
| `CBOS_ORCHESTRATOR_LISTENER_PORT` | `32205` | WebSocket server port |
| `CBOS_ORCHESTRATOR_AUTO_ANSWER_THRESHOLD` | `0.95` | Auto-answer threshold |
| `CBOS_ORCHESTRATOR_SUGGESTION_THRESHOLD` | `0.80` | Suggestion threshold |
| `CBOS_ORCHESTRATOR_AUTO_ANSWER_ENABLED` | `false` | Enable auto-answering |

## Files

| File | Description |
|------|-------------|
| `~/.cbos/patterns.db` | SQLite database with pattern metadata |
| `~/.cbos/vectors.bin` | vectl vector store (100MB default) |
| `~/.cbos/vectors.log` | vectl operation log |

## Dependencies

- **Python 3.10+** (tested with 3.13.3)
- **vectl** - Vector clustering store (included as git submodule)
- **CBAI API** - Embedding generation service

## Troubleshooting

### "No similar patterns found"
- Run `cbos-patterns build` to populate the database
- Lower the threshold: `--threshold 0.5`
- Check stats: `cbos-patterns stats`

### "Connection refused"
- Ensure CBOS server is running: `cd ts && pnpm run server`
- Check port: default is 32205

### "No module named 'vector_store'"
- Rebuild vectl: `cd extern/vectl && ./build.sh`
- Reinstall: `pip install -e extern/vectl`

### Slow embedding generation
- Reduce batch size: `--batch-size 10`
- Check CBAI API connectivity

## Examples

### Build and Query Workflow
```bash
# Initial setup
cbos-patterns build

# Check what was extracted
cbos-patterns stats

# Find similar questions
cbos-patterns query "How should I handle authentication?"

# Text search
cbos-patterns search "auth"
```

### Live Monitoring
```bash
# Terminal 1: Watch events
cbos-patterns watch

# Terminal 2: Run TUI
cd ts && pnpm run tui

# Or: Listen with pattern matching
cbos-patterns listen -v
```

### Auto-Answer Mode (Use with Caution)
```bash
# Enable auto-answering for very high confidence matches
cbos-patterns listen --auto-answer --auto-threshold 0.98

# Lower thresholds for more aggressive matching
cbos-patterns listen --auto-answer --auto-threshold 0.90 --suggest-threshold 0.70
```
