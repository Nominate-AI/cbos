# CBOS Orchestrator Usage Guide

The CBOS Orchestrator provides pattern-based intelligence for Claude Code sessions. It has two main capabilities:

1. **Pattern Store** - Extracts decision patterns from conversation history, stores them with embeddings, and can suggest or auto-answer similar questions in real-time.

2. **Skill Store** - Defines reusable multi-step workflows (release, deploy, test, etc.) that can be triggered by natural language patterns.

## Quick Start

```bash
# Activate environment
source ~/.pyenv/versions/nominates/bin/activate

# Build pattern database from conversation logs
cbos-patterns build

# List available skills
cbos-patterns skills list

# Watch live session events
cbos-patterns watch

# Listen with pattern matching and skill detection
cbos-patterns listen --skills
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

Listen to sessions and match patterns in real-time. When questions are detected, queries the pattern database for similar historical questions. Can also detect skill triggers from user input.

```bash
# Listen with pattern matching (suggestions only)
cbos-patterns listen

# Enable auto-answering for high-confidence matches
cbos-patterns listen --auto-answer

# Enable skill detection
cbos-patterns listen --skills

# Adjust thresholds
cbos-patterns listen --auto-threshold 0.90 --suggest-threshold 0.75

# Adjust skill detection threshold
cbos-patterns listen --skills --skill-threshold 0.85

# Verbose mode (show all session updates)
cbos-patterns listen -v

# Connect to different port
cbos-patterns listen -p 32206

# Full featured: patterns + skills + auto-answer
cbos-patterns listen --auto-answer --skills -v
```

**Thresholds:**
- `--auto-threshold` (default: 0.95): Similarity score required for auto-answering
- `--suggest-threshold` (default: 0.80): Similarity score required for logging suggestions
- `--skill-threshold` (default: 0.80): Confidence required for skill detection

**Sample output:**
```
Starting orchestrator listener...
Connecting to: ws://localhost:32205
Auto-answer: False
Auto-answer threshold: 95%
Suggestion threshold: 80%
Skill detection: True
Skill threshold: 80%

Connected to CBOS server
Listening for questions and skills... (Ctrl+C to stop)

[AUTH] Question: Which authentication method should we use?
  Options: JWT, OAuth2, Session-based
[AUTH] Suggestion (87%): Use JWT with refresh tokens
[BACKEND] Question: Should I proceed with this refactor?
[BACKEND] Auto-answered: Yes, proceed with the refactor
[DEPLOY] Skill: deploy (95%)
  Params: env=staging, skip_tests=false
```

---

## Skills

Skills are reusable multi-step workflows that can be triggered by natural language patterns. Unlike patterns (single Q&A), skills execute sequences of commands.

### `cbos-patterns skills list`

List all available skills from all sources (built-in, user, project).

```bash
# List all skills
cbos-patterns skills list

# Output as JSON
cbos-patterns skills list --json
```

**Sample output:**
```
                    Available Skills (9 total)
┏━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name        ┃ Version ┃ Description                 ┃ Triggers             ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ commit      │ 1.0.0   │ Git commit workflow...      │ commit and push, ... │
│ deploy      │ 1.0.0   │ Deploy to staging/prod      │ deploy to {env}, ... │
│ release     │ 1.0.0   │ Release with version bump   │ release v{version}   │
│ test        │ 1.0.0   │ Run tests (pytest/npm)      │ run tests, ...       │
└─────────────┴─────────┴─────────────────────────────┴──────────────────────┘
```

### `cbos-patterns skills show <name>`

Show detailed information about a specific skill.

```bash
# Show skill details
cbos-patterns skills show release

# Output as JSON
cbos-patterns skills show deploy --json
```

**Sample output:**
```
release v1.0.0
Release a new version with version bump, commit, tag, and push

Triggers:
  • release v{version} (confidence: 0.95)
  • release {version} (confidence: 0.9)
  • bump version to {version} (confidence: 0.85)

Parameters:
  • version*: semver
    Version number (e.g., 1.2.3)
  • message: string (default: Release {version})
    Release message

Steps:
  1. [edit] bump-pyproject
     Bump version in pyproject.toml
  2. [edit] bump-init
     Bump version in __init__.py
  3. [bash] stage
     Stage all changes
  4. [bash] commit
     Create release commit
  5. [bash] tag
     Create version tag
  6. [bash] push
     Push commit and tag

Preconditions:
  • git status --porcelain
    Working directory must be clean
```

### `cbos-patterns skills match <text>`

Find skills that match a given input text. Useful for testing trigger patterns.

```bash
# Find matching skills
cbos-patterns skills match "deploy to staging"

# With result limit
cbos-patterns skills match "release v1.2.3" --limit 3
```

**Sample output:**
```
Matching skills for: deploy to staging

deploy (95%)
  Trigger: deploy to {env}
  Description: Deploy a service to staging or production
  Extracted params: {'env': 'staging', 'skip_tests': 'false'}
```

### `cbos-patterns skills mine`

Mine potential skills from Claude Code conversation logs by analyzing tool call sequences.

```bash
# Mine all conversations
cbos-patterns skills mine

# Filter by project
cbos-patterns skills mine -p myproject

# Verbose output (show examples)
cbos-patterns skills mine -v

# Output as JSON
cbos-patterns skills mine --json
```

**Sample output:**
```
Mining skills from conversation logs...
Scanning: /home/user/.claude/projects

Found 47 potential skills

release: 12 occurrences
service: 8 occurrences
commit: 23 occurrences
test: 4 occurrences

Summary:
  Total candidates: 47
  Unique skill types: 4
```

## Built-in Skills

The orchestrator ships with 9 built-in skills:

| Skill | Description | Example Triggers |
|-------|-------------|------------------|
| `release` | Version bump, commit, tag, push | "release v1.2.3", "bump to 2.0.0" |
| `deploy` | Deploy to staging/production | "deploy to staging", "push to production" |
| `service` | systemctl operations | "restart nginx", "check status of api" |
| `commit` | Git add, commit, push | "commit and push", "save changes" |
| `test` | Run pytest or npm test | "run tests", "run pytest" |
| `format` | Ruff format and lint | "format code", "run ruff" |
| `pr` | Create pull request | "create pr", "open pull request" |
| `issue` | Create GitHub issue | "create issue", "file issue" |
| `maintenance` | Full cleanup cycle | "run maintenance", "cleanup project" |

## Skill Sources

Skills are loaded from three locations (in priority order):

1. **Project skills**: `.cbos/skills/*.yaml` - Project-specific workflows
2. **User skills**: `~/.cbos/skills/*.yaml` - Personal global workflows
3. **Built-in skills**: `orchestrator/skills/*.yaml` - Shipped with orchestrator

Higher priority sources override lower priority when skill names conflict.

## Creating Custom Skills

Create a YAML file in `~/.cbos/skills/` or `.cbos/skills/`:

```yaml
# ~/.cbos/skills/my-deploy.yaml
name: my-deploy
version: "1.0.0"
description: Custom deployment workflow

triggers:
  - pattern: "deploy {service} to {env}"
    confidence: 0.9
  - pattern: "push {service}"
    confidence: 0.8

parameters:
  - name: service
    type: string
    description: Service to deploy
    required: true
  - name: env
    type: choice
    choices: ["staging", "production"]
    default: "staging"

preconditions:
  - command: "git status --porcelain"
    expect: ""
    message: "Working directory must be clean"

steps:
  - name: build
    type: bash
    command: "docker build -t {service} ."

  - name: push
    type: bash
    command: "docker push registry/{service}:latest"

  - name: deploy
    type: bash
    command: "kubectl rollout restart deployment/{service} -n {env}"

  - name: verify
    type: bash
    command: "kubectl rollout status deployment/{service} -n {env}"
    expect_exit: 0

postconditions:
  - command: "curl -s http://{service}.{env}/health"
    expect: "ok"
    message: "Health check should pass"
```

### Step Types

| Type | Description | Fields |
|------|-------------|--------|
| `bash` | Run shell command | `command`, `expect_exit` |
| `edit` | Edit file with regex | `file`, `pattern`, `replacement` |
| `read` | Read file content | `file` |
| `confirm` | Ask user confirmation | `message` |
| `branch` | Conditional execution | `condition`, `then_steps`, `else_steps` |

### Parameter Types

| Type | Description |
|------|-------------|
| `string` | Any text value |
| `semver` | Semantic version (1.2.3) |
| `path` | File or directory path |
| `choice` | One of predefined options |
| `bool` | true/false |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        cbos-patterns CLI                            │
├─────────────────────────────────────────────────────────────────────┤
│  build │ query │ search │ stats │ watch │ listen │ skills          │
└───┬────┴───┬───┴────┬───┴───┬───┴───┬───┴───┬────┴───┬─────────────┘
    │        │        │       │       │       │        │
    ▼        ▼        ▼       ▼       ▼       ▼        ▼
┌───────────────────────────────────┐ ┌────────────────────────────────┐
│          PatternStore             │ │        SkillRegistry           │
│  - Pattern CRUD via SQLite        │ │  - YAML skill definitions      │
│  - Vector similarity via vectl    │ │  - Trigger pattern matching    │
│  - Embedding generation via CBAI  │ │  - Parameter extraction        │
└────────────┬──────────────────────┘ └───────────────┬────────────────┘
             │                                        │
┌────────────▼─────────────┐  ┌───────────────────────▼────────────────┐
│ SQLite + vectl           │  │ YAML Files                             │
│ - patterns.db            │  │ - orchestrator/skills/*.yaml (builtin) │
│ - vectors.bin            │  │ - ~/.cbos/skills/*.yaml (user)         │
└──────────────────────────┘  │ - .cbos/skills/*.yaml (project)        │
                              └────────────────────────────────────────┘
```

### Unified Listener Flow

```
CBOS WebSocket Server (port 32205)
        │
        ├──── formatted_event (category: question)
        │            │
        │            ▼
        │     PatternStore.query_similar_text()
        │       - >= 95%: Auto-answer
        │       - >= 80%: Suggest
        │
        └──── user_input
                     │
                     ▼
              SkillRegistry.find_by_trigger()
                - Match patterns
                - Extract params
                - Fire on_skill_match callback
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
| `~/.cbos/skills/*.yaml` | User-defined global skills |
| `.cbos/skills/*.yaml` | Project-specific skills |
| `orchestrator/skills/*.yaml` | Built-in skills |

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
