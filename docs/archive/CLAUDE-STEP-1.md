# CLAUDE.md - Pattern Extraction Task

## Mission

Extract decision patterns from ClaudeCode session logs (~1 month of data) to bootstrap CBOS’s auto-responder pattern store. This is the foundation for automating 60-70% of routine `AskUserQuestion` interrupts.

## Context

You’re building the data pipeline for CBOS (Claude Code Operating System), an orchestration layer that coordinates multiple ClaudeCode sessions. The pattern store will learn from historical human responses to auto-answer similar questions in the future.

## Source Data

- **Location**: `~/.claude/projects/**/*.jsonl`
- **Format**: JSONL conversation logs from ClaudeCode sessions
- **Target**: Find all `AskUserQuestion` → user response pairs

## Deliverables

### 1. `scripts/extract_decisions.py`

Extract decision patterns from JSONL logs.

**Requirements:**

- Recursively scan `~/.claude/projects/` for `.jsonl` files
- Find `AskUserQuestion` tool use events
- Pair with the subsequent user response
- Extract 3-5 messages before/after for context
- Capture Claude’s thinking block if available
- Classify question type using heuristics
- Output as structured JSONL

**Question Type Classification:**

|Type           |Pattern Examples                             |Expected %|
|---------------|---------------------------------------------|----------|
|`permission`   |“Should I proceed/continue/run this”         |~40%      |
|`clarification`|“Which/what do you want”, “Could you clarify”|~25%      |
|`decision`     |“Option A or B”, “X vs Y”                    |~20%      |
|`blocking`     |“I need X to continue”, “Missing Y”          |~10%      |
|`error`        |“Failed, should I retry”, “Error occurred”   |~5%       |

**Output Schema:**

```python
{
    "id": "uuid4",
    "question": "The AskUserQuestion content",
    "question_type": "permission|clarification|decision|blocking|error",
    "context_before": ["up to 5 preceding messages"],
    "context_after": ["up to 3 following messages"],
    "user_answer": "The human's response",
    "thinking": "Claude's thinking block if present",
    "project": "project-name from path",
    "session_id": "session identifier",
    "timestamp": "ISO8601 from log",
    "source_file": "path to source jsonl"
}
```

**CLI Interface:**

```bash
python scripts/extract_decisions.py \
  --source ~/.claude/projects \
  --output ~/.cbos/patterns/raw.jsonl \
  --include-thinking \
  --context-before 5 \
  --context-after 3
```

### 2. `scripts/build_patterns.py`

Build the SQLite pattern database with embeddings.

**Requirements:**

- Read extracted JSONL from step 1
- Deduplicate near-identical questions (fuzzy match, >90% similarity)
- Create SQLite database at `~/.cbos/patterns.db`
- Generate embeddings using `nomic-embed-text` via Ollama
- Build similarity search index
- Output statistics

**SQLite Schema:**

```sql
CREATE TABLE patterns (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    question_type TEXT,
    context_before TEXT,  -- JSON array
    context_after TEXT,   -- JSON array
    user_answer TEXT NOT NULL,
    thinking TEXT,
    project TEXT,
    session_id TEXT,
    timestamp TEXT,
    source_file TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE embeddings (
    pattern_id TEXT PRIMARY KEY REFERENCES patterns(id),
    embedding BLOB,  -- numpy array serialized
    model TEXT DEFAULT 'nomic-embed-text'
);

CREATE INDEX idx_question_type ON patterns(question_type);
CREATE INDEX idx_project ON patterns(project);
CREATE INDEX idx_timestamp ON patterns(timestamp);
```

**CLI Interface:**

```bash
python scripts/build_patterns.py \
  --input ~/.cbos/patterns/raw.jsonl \
  --db ~/.cbos/patterns.db \
  --embedding-model nomic-embed-text
```

### 3. `scripts/query_patterns.py`

Query the pattern store for similar questions.

**Requirements:**

- Load pattern database
- Generate embedding for query
- Cosine similarity search
- Return top-k matches with confidence scores

**CLI Interface:**

```bash
python scripts/query_patterns.py "Should I proceed with the refactor?"
# Returns top 5 similar patterns with answers and confidence
```

### 4. Statistics & Validation

After building, output `~/.cbos/extraction_stats.json`:

```json
{
    "total_files_scanned": 150,
    "total_patterns_extracted": 487,
    "patterns_after_dedup": 412,
    "by_question_type": {
        "permission": 165,
        "clarification": 103,
        "decision": 82,
        "blocking": 41,
        "error": 21
    },
    "by_project": {
        "cbos": 89,
        "other-project": 45
    },
    "date_range": {
        "earliest": "2024-12-10T...",
        "latest": "2025-01-10T..."
    }
}
```

## File Structure

Create this structure:

```
~/.cbos/
├── patterns/
│   └── raw.jsonl
├── patterns.db
└── extraction_stats.json

{project_root}/
└── scripts/
    ├── extract_decisions.py
    ├── build_patterns.py
    └── query_patterns.py
```

## Dependencies

```
# Add to requirements or install directly
ollama  # For embeddings via local Ollama
numpy   # For cosine similarity
```

Verify Ollama is running and has `nomic-embed-text`:

```bash
ollama list | grep nomic
# If not present: ollama pull nomic-embed-text
```

## Constraints

- **DO NOT** modify any files in `~/.claude/` - read only
- Create `~/.cbos/` directory if it doesn’t exist
- Handle malformed JSONL gracefully (skip with warning)
- Support incremental extraction (don’t re-process already extracted)
- Keep memory usage reasonable for large log files

## Success Criteria

1. ✅ Parse all JSONL files without crashing
1. ✅ Extract 100+ decision patterns
1. ✅ Question type classification matches expected distribution (roughly)
1. ✅ Embeddings generated for all patterns
1. ✅ Query returns relevant results in <2 seconds
1. ✅ Statistics output validates the extraction

## Execution Order

1. First, explore the JSONL structure to understand the schema
1. Build `extract_decisions.py` and run extraction
1. Build `build_patterns.py` and create the database
1. Build `query_patterns.py` and validate with test queries
1. Review statistics and sample patterns for quality

## Notes

- The thinking blocks in Claude’s responses often contain valuable reasoning about why a decision was made - prioritize capturing these
- Some questions may have multi-turn responses - capture the first substantive answer
- Watch for edge cases: cancelled questions, timeouts, empty responses
