# CBOS Intelligence Layer - THE PLAN

## Vision

Transform CBOS from a passive session monitor into an **intelligent orchestration system** that actively helps manage multiple Claude Code sessions through AI-powered analysis, prioritization, and response assistance.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CBOS TUI                                       │
│  ┌─────────────┐  ┌──────────────────┐  ┌─────────────────────────────────┐ │
│  │  Sessions   │  │  AI Suggestions  │  │  Priority Queue / Smart View   │ │
│  │  ● AUTH     │  │  ┌────────────┐  │  │  1. 🔴 AUTH - needs decision   │ │
│  │  ◐ INTEL    │  │  │ Suggested  │  │  │  2. 🟡 DOCS - clarification    │ │
│  │  ○ DOCS     │  │  │ Response:  │  │  │  3. 🟢 INTEL - routine         │ │
│  │             │  │  │ "yes, ..." │  │  │                                 │ │
│  └─────────────┘  │  └────────────┘  │  └─────────────────────────────────┘ │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CBOS API (port 32205)                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                      Intelligence Service                               ││
│  │  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌─────────────┐ ││
│  │  │ ResponseDraft │ │ Summarizer    │ │ Prioritizer   │ │ Embeddings  │ ││
│  │  │ Generator     │ │               │ │               │ │ Store       │ ││
│  │  └───────────────┘ └───────────────┘ └───────────────┘ └─────────────┘ ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      CBAI Service (ai.nominate.ai)                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ /chat       │  │ /summarize  │  │ /topics     │  │ /embed              │ │
│  │ mistral/    │  │             │  │             │  │ nomic-embed-text    │ │
│  │ claude      │  │             │  │             │  │ 768-dim vectors     │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Feature 1: Auto-Suggest Responses

### Purpose
When a Claude session is waiting for input, analyze the question and generate a suggested response that the user can accept, edit, or reject.

### Implementation

#### New Endpoint: `POST /sessions/{slug}/suggest`

```python
@app.post("/sessions/{slug}/suggest")
async def suggest_response(slug: str) -> SuggestionResponse:
    """Generate AI-suggested response for a waiting session"""
    session = store.get(slug)
    if not session or session.state != SessionState.WAITING:
        raise HTTPException(400, "Session not waiting for input")

    # Get context: last N lines of buffer + the question
    buffer = store.get_buffer(slug, lines=50)
    question = session.last_question

    # Call CBAI to generate suggestion
    suggestion = await intelligence.generate_suggestion(
        question=question,
        context=buffer,
        session_slug=slug
    )

    return SuggestionResponse(
        slug=slug,
        question=question,
        suggested_response=suggestion.response,
        confidence=suggestion.confidence,
        reasoning=suggestion.reasoning
    )
```

#### Intelligence Service

```python
# cbos/intelligence/suggestions.py

class SuggestionGenerator:
    """Generate response suggestions using CBAI"""

    SYSTEM_PROMPT = """You are an assistant helping a developer respond to Claude Code.

Claude Code is asking a question and waiting for input. Based on the context
and question, suggest a helpful response.

Guidelines:
- Be concise - most responses are short confirmations or brief instructions
- If Claude is asking for permission, usually "yes" or "y" is appropriate
- If Claude needs clarification, provide specific guidance
- If unsure, say so and offer options

Respond with JSON:
{
  "response": "your suggested response",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}"""

    async def generate(self, question: str, context: str) -> Suggestion:
        response = await self.cbai.chat(
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}
            ],
            provider="ollama",  # Fast local inference
            model="mistral-small3.2:latest"
        )
        return Suggestion.parse(response)
```

#### TUI Integration

- New keybinding: `s` - Show suggestion for selected session
- Display suggestion in a panel below the buffer
- `Enter` to accept, `e` to edit, `Esc` to dismiss

---

## Feature 2: Session Summarization

### Purpose
Provide quick summaries of what each session is working on, visible in the session list and detailed view.

### Implementation

#### New Endpoint: `GET /sessions/{slug}/summary`

```python
@app.get("/sessions/{slug}/summary")
async def get_session_summary(slug: str) -> SummaryResponse:
    """Get AI-generated summary of session activity"""
    buffer = store.get_buffer(slug, lines=200)

    summary = await intelligence.summarize_session(buffer)

    return SummaryResponse(
        slug=slug,
        summary=summary.short,      # 1-line for list view
        detailed=summary.detailed,  # 2-3 sentences for detail view
        topics=summary.topics,      # Key themes
        last_action=summary.last_action
    )
```

#### Caching Strategy

```python
class SummaryCache:
    """Cache summaries to avoid redundant API calls"""

    def __init__(self, ttl_seconds: int = 30):
        self._cache: dict[str, tuple[Summary, float]] = {}
        self.ttl = ttl_seconds

    async def get(self, slug: str, buffer_hash: str) -> Optional[Summary]:
        cached = self._cache.get(slug)
        if cached and cached[1] > time.time() - self.ttl:
            if cached[0].buffer_hash == buffer_hash:
                return cached[0]
        return None
```

#### TUI Integration

- Show 1-line summary next to session name in list
- Full summary in content header when session selected
- Refresh summary on demand with `S` keybinding

---

## Feature 3: Priority Queue

### Purpose
Rank waiting sessions by urgency and importance, helping users focus on what matters most.

### Implementation

#### Priority Factors

| Factor | Weight | Detection Method |
|--------|--------|------------------|
| Time waiting | 0.3 | `now - last_activity` |
| Question type | 0.3 | AI classification |
| Error severity | 0.2 | Pattern matching |
| User preference | 0.2 | Configured priorities |

#### Question Types (AI-classified)

```python
class QuestionType(Enum):
    PERMISSION = "permission"       # "Should I proceed?", "Run this command?"
    DECISION = "decision"           # "Which approach?", "Option A or B?"
    CLARIFICATION = "clarification" # "What do you mean by...?"
    ERROR = "error"                 # "Failed to...", "Error occurred"
    INFORMATION = "information"     # "What is the...?", "Where should...?"
```

#### New Endpoint: `GET /sessions/prioritized`

```python
@app.get("/sessions/prioritized")
async def get_prioritized_sessions() -> list[PrioritizedSession]:
    """Get waiting sessions ranked by priority"""
    waiting = store.waiting()

    prioritized = []
    for session in waiting:
        priority = await intelligence.calculate_priority(session)
        prioritized.append(PrioritizedSession(
            session=session,
            priority_score=priority.score,
            priority_reason=priority.reason,
            question_type=priority.question_type,
            suggested_action=priority.suggested_action
        ))

    return sorted(prioritized, key=lambda p: p.priority_score, reverse=True)
```

#### TUI Integration

- New view mode: `p` toggles priority view
- Shows waiting sessions sorted by priority
- Color-coded urgency indicators
- Priority reason shown on hover/select

---

## Feature 4: Cross-Session Context (Embeddings)

### Purpose
Detect when sessions are working on related tasks, enabling context sharing and conflict detection.

### Implementation

#### Embedding Storage

```python
# cbos/intelligence/embeddings.py

class SessionEmbeddingStore:
    """Store and query session context embeddings"""

    def __init__(self, cbai_url: str):
        self.cbai = CBAIClient(cbai_url)
        self._embeddings: dict[str, np.ndarray] = {}
        self._contexts: dict[str, str] = {}

    async def update(self, slug: str, buffer: str) -> None:
        """Update embedding for a session's current context"""
        # Summarize first to reduce token count
        summary = await self.cbai.summarize(buffer, max_length=500)

        # Generate embedding
        embedding = await self.cbai.embed(summary)

        self._embeddings[slug] = np.array(embedding)
        self._contexts[slug] = summary

    def find_related(self, slug: str, threshold: float = 0.7) -> list[RelatedSession]:
        """Find sessions with similar context"""
        if slug not in self._embeddings:
            return []

        target = self._embeddings[slug]
        related = []

        for other_slug, other_embed in self._embeddings.items():
            if other_slug == slug:
                continue

            similarity = cosine_similarity(target, other_embed)
            if similarity >= threshold:
                related.append(RelatedSession(
                    slug=other_slug,
                    similarity=similarity,
                    context_summary=self._contexts[other_slug]
                ))

        return sorted(related, key=lambda r: r.similarity, reverse=True)
```

#### New Endpoint: `GET /sessions/{slug}/related`

```python
@app.get("/sessions/{slug}/related")
async def get_related_sessions(slug: str) -> list[RelatedSession]:
    """Find sessions working on similar tasks"""
    return intelligence.embeddings.find_related(slug)
```

#### Use Cases

1. **Context Sharing**: "AUTH and TENANT are both working on user permissions"
2. **Conflict Detection**: "DOCS and API are modifying the same files"
3. **Task Routing**: "This task is similar to what INTEL is doing"

---

## Feature 5: Smart Routing

### Purpose
When starting a new task, suggest which existing session should handle it or recommend creating a new one.

### Implementation

#### New Endpoint: `POST /sessions/route`

```python
@app.post("/sessions/route")
async def route_task(request: RouteRequest) -> RouteResponse:
    """Suggest which session should handle a task"""
    task_description = request.task

    # Embed the task
    task_embedding = await intelligence.embed(task_description)

    # Find best matching session
    sessions = store.all()
    candidates = []

    for session in sessions:
        if session.state == SessionState.ERROR:
            continue

        similarity = intelligence.embeddings.similarity(
            task_embedding,
            session.slug
        )

        candidates.append(RoutingCandidate(
            slug=session.slug,
            match_score=similarity,
            current_state=session.state,
            summary=await intelligence.get_summary(session.slug)
        ))

    # Rank and recommend
    ranked = sorted(candidates, key=lambda c: c.match_score, reverse=True)

    best = ranked[0] if ranked and ranked[0].match_score > 0.6 else None

    return RouteResponse(
        recommended_session=best.slug if best else None,
        recommendation_reason=generate_reason(best, task_description),
        alternatives=ranked[1:3],
        suggest_new=best is None or best.match_score < 0.6
    )
```

#### TUI Integration

- New command: `n` - New task routing
- Prompt for task description
- Show recommended session with explanation
- Quick action to send task to selected session

---

## Data Models

```python
# cbos/intelligence/models.py

class Suggestion(BaseModel):
    response: str
    confidence: float
    reasoning: str

class Summary(BaseModel):
    short: str           # "Implementing auth middleware"
    detailed: str        # 2-3 sentence description
    topics: list[str]    # ["authentication", "middleware", "FastAPI"]
    last_action: str     # "Writing test cases"
    buffer_hash: str     # For cache invalidation

class Priority(BaseModel):
    score: float         # 0.0 - 1.0
    reason: str          # "Error requiring immediate attention"
    question_type: QuestionType
    wait_time: int       # Seconds waiting
    suggested_action: str

class RelatedSession(BaseModel):
    slug: str
    similarity: float
    context_summary: str
    shared_topics: list[str]

class RoutingCandidate(BaseModel):
    slug: str
    match_score: float
    current_state: SessionState
    summary: str
    availability: str    # "idle", "busy", "waiting"
```

---

## Configuration

```python
# cbos/core/config.py

class IntelligenceSettings(BaseSettings):
    cbai_url: str = "https://ai.nominate.ai"

    # Model selection
    suggestion_model: str = "mistral-small3.2:latest"
    suggestion_provider: str = "ollama"

    summary_model: str = "mistral-small3.2:latest"
    priority_model: str = "mistral-small3.2:latest"

    # Use Claude for complex reasoning
    complex_reasoning_model: str = "claude-sonnet-4-5-20250929"
    complex_reasoning_provider: str = "claude"

    # Caching
    summary_cache_ttl: int = 30
    embedding_update_interval: int = 60

    # Thresholds
    suggestion_confidence_threshold: float = 0.7
    related_session_threshold: float = 0.7
    routing_match_threshold: float = 0.6
```

---

## Implementation Phases

### Phase 1: Foundation (Core Intelligence Service)
- [ ] Create `cbos/intelligence/` module
- [ ] Implement CBAI client wrapper
- [ ] Add configuration for AI settings
- [ ] Basic suggestion generation endpoint

### Phase 2: Suggestions
- [ ] Implement `SuggestionGenerator`
- [ ] Add `/sessions/{slug}/suggest` endpoint
- [ ] TUI integration with suggestion panel
- [ ] Accept/edit/reject flow

### Phase 3: Summarization
- [ ] Implement `SessionSummarizer`
- [ ] Add summary caching
- [ ] Add `/sessions/{slug}/summary` endpoint
- [ ] TUI integration in session list and detail

### Phase 4: Priority Queue
- [ ] Implement `PriorityCalculator`
- [ ] Question type classification
- [ ] Add `/sessions/prioritized` endpoint
- [ ] TUI priority view mode

### Phase 5: Cross-Session Context
- [ ] Implement `SessionEmbeddingStore`
- [ ] Background embedding updates
- [ ] Add `/sessions/{slug}/related` endpoint
- [ ] TUI related sessions indicator

### Phase 6: Smart Routing
- [ ] Implement routing logic
- [ ] Add `/sessions/route` endpoint
- [ ] TUI new task flow
- [ ] Integration with session creation

---

## API Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/sessions/{slug}/suggest` | POST | Generate response suggestion |
| `/sessions/{slug}/summary` | GET | Get session summary |
| `/sessions/prioritized` | GET | Get priority-ranked waiting sessions |
| `/sessions/{slug}/related` | GET | Find related sessions |
| `/sessions/route` | POST | Suggest session for new task |
| `/intelligence/health` | GET | AI service health check |

---

## TUI Keybindings (New)

| Key | Action |
|-----|--------|
| `s` | Show AI suggestion for selected session |
| `S` | Refresh summary |
| `p` | Toggle priority view |
| `n` | New task routing |
| `x` | Show related sessions |

---

## Success Metrics

1. **Response Time**: Suggestions generated in < 2 seconds
2. **Suggestion Accuracy**: > 70% of suggestions accepted without edit
3. **Priority Accuracy**: User agrees with top priority > 80% of time
4. **Related Detection**: False positive rate < 20%
5. **Routing Accuracy**: Recommended session is correct > 75% of time

---

## Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    # ... existing ...
    "numpy>=1.24",      # For embedding operations
    "httpx>=0.24",      # Already present, for CBAI calls
]
```

---

## Security Considerations

1. **API Key Management**: CBAI credentials stored in environment, not code
2. **Rate Limiting**: Implement backoff for CBAI calls
3. **Data Sanitization**: Strip sensitive content before sending to AI
4. **Local First**: Use Ollama (local) by default, Claude for complex cases

---

## Next Steps

1. Review and approve this plan
2. Create `cbos/intelligence/` module structure
3. Implement CBAI client wrapper
4. Start with Phase 1: Basic suggestion generation
