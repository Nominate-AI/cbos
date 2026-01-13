# CBOS Skills Architecture

## The Insight

Currently we map: **Question → Answer** (reactive)

We should also map: **Text Chunk → Workflow** (proactive)

```
┌─────────────────────────────────────────────────────────────────┐
│                     Current: Pattern Store                       │
│                                                                  │
│   "Should I proceed with the commit?" → "Yes"                   │
│   "Which database?" → "PostgreSQL"                               │
│                                                                  │
│   = Single Q&A pairs, auto-answer similar questions             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      New: Skill Store                            │
│                                                                  │
│   "Release v1.2.3" → [bump version, commit, tag, push]          │
│   "Deploy to staging" → [build, test, deploy, verify]           │
│   "Run maintenance" → [cleanup, format, lint, commit]           │
│                                                                  │
│   = Multi-step workflows, execute entire sequences              │
└─────────────────────────────────────────────────────────────────┘
```

## Skill vs Pattern Comparison

| Aspect | Pattern (Current) | Skill (New) |
|--------|------------------|-------------|
| Trigger | Question asked | User request or detected opportunity |
| Response | Single answer | Multi-step workflow |
| Parameters | None | Named, typed (version, service, env) |
| Scope | Context-dependent | Reusable across projects |
| Authoring | Extracted from logs | Defined or mined |
| Execution | Auto-answer | Step-by-step with rollback |

## Skill Definition Model

```python
class SkillTrigger(BaseModel):
    """How to detect when a skill should be suggested"""
    pattern: str           # Regex or semantic pattern
    embedding: list[float] | None  # For similarity matching
    confidence: float = 0.8

class SkillParameter(BaseModel):
    """A parameter for a skill"""
    name: str
    type: Literal["string", "semver", "path", "choice", "bool"]
    description: str
    required: bool = True
    default: str | None = None
    choices: list[str] | None = None  # For type="choice"

class SkillStep(BaseModel):
    """A single step in a skill workflow"""
    name: str
    type: Literal["bash", "edit", "read", "confirm", "branch"]

    # For type="bash"
    command: str | None = None
    expect_exit: int | None = None

    # For type="edit"
    file: str | None = None
    pattern: str | None = None
    replacement: str | None = None

    # For type="confirm"
    message: str | None = None

    # For type="branch"
    condition: str | None = None
    then_steps: list[str] | None = None
    else_steps: list[str] | None = None

class SkillCondition(BaseModel):
    """Pre/post condition for a skill"""
    command: str
    expect: str | None = None
    expect_exit: int | None = None
    message: str

class Skill(BaseModel):
    """A reusable multi-step workflow"""
    id: int | None = None
    name: str                          # e.g., "release"
    version: str = "1.0.0"
    description: str

    # How to detect this skill should run
    triggers: list[SkillTrigger]

    # Input parameters
    parameters: list[SkillParameter] = []

    # Execution
    preconditions: list[SkillCondition] = []
    steps: list[SkillStep]
    postconditions: list[SkillCondition] = []

    # Metadata
    project_scope: str | None = None   # None = global, else project-specific
    author: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)

    # Source tracking (if mined from logs)
    source_sessions: list[str] = []
    confidence: float = 1.0  # 1.0 for authored, <1.0 for mined
```

## Skill File Format (YAML)

```yaml
# ~/.cbos/skills/release.yaml
name: release
version: "1.0.0"
description: Release a new version with version bump, commit, tag, and push

triggers:
  - pattern: "release v?{version}"
  - pattern: "bump.*to.*{version}"
  - pattern: "publish.*{version}"

parameters:
  - name: version
    type: semver
    description: Version number (e.g., 1.2.3)
    required: true
  - name: message
    type: string
    description: Release message
    default: "Release {version}"

preconditions:
  - command: "git status --porcelain"
    expect: ""
    message: "Working directory must be clean"
  - command: "git branch --show-current"
    expect: "main"
    message: "Must be on main branch"

steps:
  - name: bump-pyproject
    type: edit
    file: pyproject.toml
    pattern: 'version = "[\d.]+"'
    replacement: 'version = "{version}"'

  - name: bump-init
    type: edit
    file: "**/__init__.py"
    pattern: '__version__ = "[\d.]+"'
    replacement: '__version__ = "{version}"'

  - name: stage
    type: bash
    command: "git add -A"

  - name: commit
    type: bash
    command: 'git commit -m "v{version}: {message}"'

  - name: tag
    type: bash
    command: "git tag v{version}"

  - name: push
    type: bash
    command: "git push && git push --tags"

postconditions:
  - command: "git tag -l v{version}"
    expect: "v{version}"
    message: "Tag should exist locally"
```

## Skill Detection: Scanning for Opportunities

### 1. Sequence Mining

Scan conversation logs for **repeated tool call sequences**:

```python
class SkillMiner:
    """Mine skills from conversation logs"""

    # Signature patterns for common skills
    SIGNATURES = {
        "release": {
            "tool_sequence": [
                ("Edit", r"pyproject\.toml"),
                ("Edit", r"__init__\.py"),
                ("Bash", r"git (add|commit|tag|push)"),
            ],
            "text_patterns": [r"v?\d+\.\d+\.\d+", r"release", r"bump"],
        },
        "deploy": {
            "tool_sequence": [
                ("Bash", r"(docker|kubectl|systemctl)"),
            ],
            "text_patterns": [r"deploy", r"staging|production"],
        },
        "maintenance": {
            "tool_sequence": [
                ("Bash", r"ruff"),
                ("Edit", r"\.py$"),
                ("Bash", r"git commit"),
            ],
            "text_patterns": [r"maintenance", r"cleanup", r"format"],
        },
        "test": {
            "tool_sequence": [
                ("Bash", r"pytest|npm test|cargo test"),
            ],
            "text_patterns": [r"run tests", r"test.*pass"],
        },
    }

    def mine_session(self, session_file: Path) -> list[SkillCandidate]:
        """Find potential skills in a session"""
        messages = self._load_messages(session_file)
        tool_calls = self._extract_tool_sequence(messages)

        candidates = []
        for sig_name, sig in self.SIGNATURES.items():
            if self._matches_signature(tool_calls, sig):
                candidates.append(SkillCandidate(
                    skill_type=sig_name,
                    session=session_file,
                    tool_calls=tool_calls,
                    confidence=self._calculate_confidence(tool_calls, sig),
                ))

        return candidates
```

### 2. Semantic Clustering

Group similar conversation segments:

```python
async def cluster_workflows(sessions: list[Path]) -> list[SkillCluster]:
    """Cluster similar multi-step workflows"""

    # 1. Extract workflow segments (contiguous tool call sequences)
    segments = []
    for session in sessions:
        segments.extend(extract_workflow_segments(session))

    # 2. Generate embeddings for each segment
    embeddings = await embed_segments(segments)

    # 3. Cluster using K-means or DBSCAN
    clusters = cluster_embeddings(embeddings, min_cluster_size=3)

    # 4. For each cluster, generate a candidate skill
    return [
        SkillCluster(
            segments=cluster.segments,
            centroid=cluster.centroid,
            skill_template=generate_skill_template(cluster),
        )
        for cluster in clusters
    ]
```

### 3. Real-Time Detection

Monitor conversations for skill opportunities:

```python
class SkillDetector:
    """Detect skill invocation opportunities in real-time"""

    def __init__(self, skill_registry: SkillRegistry):
        self.registry = skill_registry
        self.trigger_embeddings = {}  # skill_name -> embedding

    async def precompute_embeddings(self):
        """Pre-compute embeddings for all skill triggers"""
        for skill in self.registry.list_skills():
            for trigger in skill.triggers:
                if trigger.embedding is None:
                    trigger.embedding = await embed(trigger.pattern)
                self.trigger_embeddings[f"{skill.name}:{trigger.pattern}"] = trigger

    async def detect(self, user_input: str) -> list[SkillMatch]:
        """Detect if user input matches any skill triggers"""
        input_embedding = await embed(user_input)

        matches = []
        for key, trigger in self.trigger_embeddings.items():
            similarity = cosine_similarity(input_embedding, trigger.embedding)
            if similarity >= trigger.confidence:
                skill_name = key.split(":")[0]
                params = self._extract_parameters(user_input, trigger.pattern)
                matches.append(SkillMatch(
                    skill=self.registry.get(skill_name),
                    trigger=trigger,
                    similarity=similarity,
                    extracted_params=params,
                ))

        return sorted(matches, key=lambda m: m.similarity, reverse=True)
```

## Architecture Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                    CBOS Orchestrator v0.3                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   User Input (WebSocket)                                        │
│         │                                                        │
│         ▼                                                        │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │              Unified Intent Classifier                   │   │
│   │                                                          │   │
│   │  1. Is this a skill invocation? → SkillDetector         │   │
│   │  2. Is this a question response? → PatternMatcher       │   │
│   │  3. Neither? → Pass through                             │   │
│   └─────────────────────────────────────────────────────────┘   │
│              │                         │                         │
│              ▼                         ▼                         │
│   ┌──────────────────┐      ┌──────────────────┐               │
│   │   Skill Engine   │      │  Pattern Engine  │               │
│   │                  │      │   (existing)     │               │
│   │  ┌────────────┐  │      │                  │               │
│   │  │ Registry   │  │      │  ┌────────────┐  │               │
│   │  │ (YAML/DB)  │  │      │  │  SQLite    │  │               │
│   │  └────────────┘  │      │  └────────────┘  │               │
│   │  ┌────────────┐  │      │  ┌────────────┐  │               │
│   │  │ Executor   │  │      │  │  vectl     │  │               │
│   │  │ (steps)    │  │      │  └────────────┘  │               │
│   │  └────────────┘  │      │                  │               │
│   └──────────────────┘      └──────────────────┘               │
│              │                         │                         │
│              └────────────┬────────────┘                         │
│                           ▼                                      │
│                  Response to Claude                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Status

### Phase 1: Core Skill Models ✅ COMPLETE (v0.2.0)
- [x] Add skill models to `models.py` - Skill, SkillTrigger, SkillStep, SkillParameter, SkillCondition
- [x] Create `skill_registry.py` for YAML loading
- [x] CLI: `cbos-patterns skills list`
- [x] CLI: `cbos-patterns skills show <name>`

### Phase 2: Skill Authoring ✅ COMPLETE (v0.2.0)
- [x] Create 9 sample skills: release, deploy, test, commit, format, service, pr, issue, maintenance
- [x] YAML skill format documented
- [x] Multi-source loading (builtin, user, project)
- [ ] CLI: `cbos-patterns skills create <name>` (deferred - manual YAML creation works)
- [ ] CLI: `cbos-patterns skills export <name>` (deferred)

### Phase 3: Skill Detection ✅ COMPLETE (v0.2.0)
- [x] Pattern matching with `find_by_trigger()`
- [x] Parameter extraction with `extract_params()`
- [x] Integrate with `OrchestratorListener` via `on_skill_match` callback
- [x] CLI: `cbos-patterns skills match <text>`
- [x] CLI flag: `cbos-patterns listen --skills`
- [ ] Pre-compute trigger embeddings (deferred - regex matching sufficient for now)

### Phase 4: Skill Mining ✅ COMPLETE (v0.2.0)
- [x] Create `skill_miner.py` with SKILL_SIGNATURES
- [x] Implement sequence pattern detection
- [x] CLI: `cbos-patterns skills mine [--project]`
- [x] Generate candidate skills from logs

### Phase 5: Skill Execution 🔜 NEXT
- [ ] Create `skill_executor.py`
- [ ] Parameter substitution in commands
- [ ] Precondition validation
- [ ] Step-by-step execution with output capture
- [ ] Rollback on failure
- [ ] CLI: `cbos-patterns skills run <name> [params]`
- [ ] Dry-run mode: `cbos-patterns skills run --dry-run`

### Phase 6: Full Integration 📋 PLANNED
- [ ] Auto-suggest skills when triggers match in listener
- [ ] WebSocket command to execute skills
- [ ] TUI skill picker/executor
- [ ] Skill execution history/logging
- [ ] Semantic trigger matching with embeddings

## Sample Skills to Bootstrap

### 1. release
Trigger: "release v{version}", "bump to {version}"
Steps: bump version files → commit → tag → push

### 2. deploy
Trigger: "deploy to {env}", "push to {env}"
Steps: build → test → deploy → verify

### 3. test
Trigger: "run tests", "test this"
Steps: pytest/npm test → report

### 4. format
Trigger: "format code", "run linter"
Steps: ruff format → ruff check --fix → commit

### 5. maintenance
Trigger: "run maintenance", "/cb-maintenance:maintain"
Steps: (the full 10-phase cycle we just ran)

### 6. commit
Trigger: "commit this", "save changes"
Steps: git status → git add → git commit

### 7. pr
Trigger: "create pr", "open pull request"
Steps: push → gh pr create

## Key Insight: Skill Discovery Heuristics

To scan existing conversations for skill-worthy patterns:

1. **Version bumps**: `version.*\d+\.\d+\.\d+` + Edit files + git commands
2. **Git workflows**: Sequences of git add/commit/push/tag
3. **Deployment**: docker/kubectl/systemctl commands
4. **Testing**: pytest/npm test/cargo test patterns
5. **Formatting**: ruff/prettier/black commands followed by commits
6. **Service management**: systemctl start/stop/restart patterns

Each detected pattern becomes a **skill candidate** that can be refined into a formal skill definition.

---

## Current Implementation Files

As of v0.2.0, the skill system consists of:

### Core Files
| File | Purpose |
|------|---------|
| `orchestrator/models.py` | Pydantic models for Skill, SkillTrigger, SkillStep, etc. |
| `orchestrator/skill_registry.py` | Loads skills from YAML, matches triggers, extracts params |
| `orchestrator/skill_miner.py` | Scans conversation logs for skill patterns |
| `orchestrator/listener.py` | WebSocket listener with `on_skill_match` callback |
| `orchestrator/cli.py` | CLI commands: `skills list/show/match/mine` |

### Built-in Skills (orchestrator/skills/)
| Skill | Triggers |
|-------|----------|
| `release.yaml` | "release v{version}", "bump to {version}" |
| `deploy.yaml` | "deploy to {env}", "push to {env}" |
| `service.yaml` | "restart {service}", "check status of {service}" |
| `commit.yaml` | "commit and push", "save changes" |
| `test.yaml` | "run tests", "run pytest" |
| `format.yaml` | "format code", "run ruff" |
| `pr.yaml` | "create pr", "open pull request" |
| `issue.yaml` | "create issue", "file issue" |
| `maintenance.yaml` | "run maintenance", "cleanup project" |

## Next Steps: Skill Executor

The next major milestone is implementing `skill_executor.py` to actually run skills:

```python
class SkillExecutor:
    """Execute skill workflows step by step"""

    async def run(
        self,
        skill: Skill,
        params: dict[str, str],
        dry_run: bool = False
    ) -> SkillResult:
        # 1. Validate all required params provided
        # 2. Check preconditions
        # 3. Execute each step in order
        # 4. Handle branching (if/then/else steps)
        # 5. Check postconditions
        # 6. Return result with outputs
```

Key considerations:
- **Parameter substitution**: Replace `{param}` in commands/files
- **Step types**: bash (subprocess), edit (file modification), confirm (user prompt)
- **Error handling**: Capture stderr, check exit codes, support rollback
- **Dry-run mode**: Show what would happen without executing
- **Output capture**: Store stdout/stderr for each step
