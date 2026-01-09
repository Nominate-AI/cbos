# Campaign Brain Maintenance Guide

This document defines maintenance standards and hygiene practices for all Campaign Brain (`cb*`) projects. It covers code maintenance, documentation, API standards, and infrastructure configuration.

---

## Phase 1: Reconnaissance

Before making changes, analyze the project:

1. **Map the current structure** - Run `tree -I '__pycache__|*.pyc|.git|.venv|venv|node_modules' -L 3`
2. **Identify the project type** - Is this a library, CLI tool, web app, or monorepo?
3. **Check for existing configs** - Look for `pyproject.toml`, `setup.py`, `setup.cfg`, `ruff.toml`, `.pre-commit-config.yaml`, `mkdocs.yml`
4. **Note the Python version** - Check `pyproject.toml`, `.python-version`, or `runtime.txt`
5. **Identify the package manager** - pip, poetry, pdm, uv, or hatch?

Report findings before proceeding.

---

## Phase 2: Archive & Cleanup

### 2.1 Create Archive Structure

```bash
mkdir -p ./archive/{logs,old_versions,deprecated,scratch}
```

### 2.2 Move Stale Files

Move to `./archive/` (preserve git history with `git mv` when possible):

- **Logs**: `*.log`, `logs/`, any timestamped output files older than 30 days
- **Old versions**: Files with patterns like `*_old.py`, `*_backup.py`, `*_v1.py`, `*.bak`
- **Deprecated code**: Anything marked `# DEPRECATED`, `# TODO: remove`, or obviously dead code
- **Scratch/experiments**: `scratch/`, `experiments/`, `sandbox/`, `tmp/`, `temp/`
- **Generated artifacts**: `build/`, `dist/`, `*.egg-info/` (these can often be deleted entirely)
- **Orphaned configs**: Old CI configs, unused Docker files, stale requirements files

### 2.3 Purge (Delete, Don't Archive)

- `__pycache__/` directories
- `.pyc`, `.pyo` files
- `.coverage`, `htmlcov/`
- `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`
- `*.DS_Store`, `Thumbs.db`
- Empty `__init__.py` files in non-package directories

### 2.4 Update .gitignore

Ensure `.gitignore` includes standard Python ignores. Use GitHub's Python template as baseline.

---

## Phase 3: Code Formatting & Style

### 3.1 Tooling Setup (Ruff-first approach)

**Ruff is the standard.** It replaces Black, isort, flake8, and most other linters in a single fast tool.

If `pyproject.toml` exists, add/update:

```toml
[tool.ruff]
target-version = "py312"  # Adjust to project's minimum Python version
line-length = 88
indent-width = 4

[tool.ruff.lint]
select = [
    "E",      # pycodestyle errors
    "W",      # pycodestyle warnings
    "F",      # Pyflakes
    "I",      # isort
    "B",      # flake8-bugbear
    "C4",     # flake8-comprehensions
    "UP",     # pyupgrade
    "ARG",    # flake8-unused-arguments
    "SIM",    # flake8-simplify
    "TCH",    # flake8-type-checking
    "PTH",    # flake8-use-pathlib
    "ERA",    # eradicate (commented-out code)
    "PL",     # Pylint
    "RUF",    # Ruff-specific rules
]
ignore = [
    "E501",   # line too long (handled by formatter)
    "PLR0913", # too many arguments
    "PLR2004", # magic value comparison
]
fixable = ["ALL"]
unfixable = []

[tool.ruff.lint.isort]
known-first-party = ["your_package_name"]
force-single-line = true

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
skip-magic-trailing-comma = false
line-ending = "auto"
docstring-code-format = true
```

### 3.2 Run Formatting

```bash
# Format all Python files
ruff format .

# Fix auto-fixable lint issues
ruff check --fix .

# Show remaining issues
ruff check .
```

### 3.3 Type Hints Hygiene

- Add type hints to all public function signatures (parameters and return types)
- Use modern syntax: `list[str]` not `List[str]`, `str | None` not `Optional[str]`
- Add `py.typed` marker file if this is a library intended for distribution

---

## Phase 4: Docstrings & Comments

### 4.1 Docstring Standard

Use **Google-style docstrings** (mkdocstrings default, most readable):

```python
def process_record(record_id: str, include_history: bool = False) -> Record:
    """Retrieve and process a record from the database.

    Fetches the record, validates required fields, and optionally
    enriches with history data.

    Args:
        record_id: Unique identifier for the record.
        include_history: Whether to include history. Defaults to False.

    Returns:
        Processed record with validated fields.

    Raises:
        RecordNotFoundError: If no record exists with the given ID.
        ValidationError: If required fields are missing or malformed.

    Example:
        >>> record = process_record("12345", include_history=True)
        >>> print(record.name)
        'Jane Doe'
    """
```

### 4.2 Docstring Coverage

Ensure docstrings exist for:

- All public modules (top of file)
- All public classes (below class definition)
- All public functions and methods
- Complex private functions (prefix with `_`)

### 4.3 Comment Cleanup

- Remove commented-out code (Ruff's ERA rule catches this)
- Convert `# TODO` comments to GitHub Issues where appropriate
- Remove obvious/redundant comments (`# increment counter` above `counter += 1`)
- Keep comments that explain *why*, remove those that explain *what*

---

## Phase 5: API Documentation Standards

Every FastAPI service must have comprehensive OpenAPI documentation.

### 5.1 API Info Section

Every API MUST include a complete `info` section:

```python
from fastapi import FastAPI

app = FastAPI(
    title="Service Name API",
    description="""
## Overview

Brief description of what this API does and who it's for.

## Key Capabilities

### Feature 1
Description of first major capability.

### Feature 2
Description of second major capability.

## How to Use This API

Step-by-step guidance for consumers.

## Rate Limits

- Endpoint X: Limit per request
- Recommended batch size: X-Y items
""",
    version="1.0.0",
    contact={
        "name": "Team Name",
        "url": "https://github.com/org/repo-name",
        "email": "team@example.com"
    },
    license_info={
        "name": "Proprietary",
        "url": "https://example.com/terms"
    },
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)
```

### 5.2 Tags (Endpoint Groupings)

Tags organize endpoints into logical categories. Each tag MUST have a description:

```python
tags_metadata = [
    {
        "name": "analysis",
        "description": """
**Analysis Operations**

Core analysis endpoints. Use these when a user asks:
- "How do these items differ from the baseline?"
- "What's unique about this segment?"
"""
    },
    {
        "name": "health",
        "description": """
**System Health & Status**

Monitor API health and configuration.
"""
    }
]

app = FastAPI(..., openapi_tags=tags_metadata)
```

### 5.3 Endpoint Documentation

Every endpoint MUST include `summary`, `description`, `tags`, and documented `responses`:

```python
@app.post(
    "/api/v1/analyze",
    tags=["analysis"],
    summary="Analyze segment against baseline",
    responses={
        200: {
            "description": "Successful analysis",
            "content": {
                "application/json": {
                    "example": {"request_id": "abc-123", "status": "complete"}
                }
            }
        },
        404: {
            "description": "No matching records found",
            "content": {
                "application/json": {
                    "example": {"detail": "No matching records found"}
                }
            }
        },
        422: {"description": "Validation error"},
        503: {"description": "Service unavailable"}
    }
)
async def analyze_segment(request: AnalysisRequest):
    """
    ## Analyze a Segment

    Compare a segment against the baseline to identify significant differences.

    ### What This Endpoint Does

    1. **Resolves IDs** - Converts identifiers to internal records
    2. **Computes statistics** - Calculates mean, median, distributions
    3. **Compares to baseline** - Identifies deviations from baseline
    4. **Flags significance** - Marks columns with significant differences

    ### Use Cases

    - **Segment Analysis**: "How do these items differ from the population?"
    - **Targeting**: "What's unique about this group?"

    ### Response Interpretation

    Start with the summary, highlight top deviations, explain categorical shifts.
    """
```

### 5.4 Request/Response Schemas

Every Pydantic model MUST include docstrings and field descriptions:

```python
from pydantic import BaseModel, Field
from typing import List

class AnalysisRequest(BaseModel):
    """Request for segment analysis."""

    ids: List[str] = Field(
        ...,
        min_length=1,
        max_length=100000,
        description="List of IDs to analyze. Maximum 100,000 per request.",
        json_schema_extra={"examples": [["ID-123", "ID-456"]]}
    )

    include_patterns: bool = Field(
        default=True,
        description="Include data quality patterns in results."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "ids": ["ID-123", "ID-456"],
                "include_patterns": True
            }
        }
```

### 5.5 Health Check Endpoint

Every API MUST expose a health check:

```python
class HealthResponse(BaseModel):
    """Health check response with component status."""

    status: str = Field(description="Overall health: 'healthy' or 'degraded'")
    model_loaded: bool = Field(description="Whether required models are loaded")
    database_connected: bool = Field(description="Database connection status")
    version: str = Field(description="API version number")

@app.get("/api/v1/health", tags=["health"], response_model=HealthResponse)
async def health_check():
    """
    ## Health Check

    Returns the current health status of the API, including:

    - **Model status** - Are required models loaded?
    - **Database status** - Is the database connection active?
    - **Version** - Current API version
    """
```

### 5.6 API Documentation Writing Style

**Do's:**
- Use **active voice**: "Analyzes segments" not "Segments are analyzed"
- Start descriptions with **action verbs**: Analyze, Get, Create, Update, Delete
- Include **realistic examples**: Use plausible data, not "foo", "bar"
- Document **edge cases**: What happens with empty input?
- Explain **why**, not just what

**Don'ts:**
- Don't use jargon without explanation
- Don't assume prior knowledge of internal systems
- Don't leave fields without descriptions
- Don't use placeholder examples ("string", 0, null)
- Don't skip error response documentation

---

## Phase 6: Documentation Organization

### 6.1 Create Docs Structure

```
./docs/
├── index.md              # Project overview
├── getting-started.md    # Installation & quickstart
├── api/                  # API reference (mkdocstrings will populate)
├── guides/               # How-to guides, tutorials
├── reference/            # Technical reference, architecture
├── contributing.md       # Contribution guidelines
└── changelog.md          # Version history
```

### 6.2 Consolidate Documentation

- Move all `.md` files from project root (except `README.md`) into appropriate `docs/` subdirectory
- Convert any `.rst` files to Markdown if the project uses mkdocs
- Move `CHANGELOG.md`, `HISTORY.md`, `CHANGES.md` to `docs/changelog.md`
- Move `CONTRIBUTING.md` to `docs/contributing.md`
- Consolidate duplicate docs

### 6.3 README.md Hygiene

Ensure `README.md` in project root contains:

- Project name and one-line description
- Badges (if applicable): CI status, PyPI version, Python versions
- Installation instructions
- Minimal usage example
- Link to full documentation

---

## Phase 7: NGINX Configuration for API Documentation

### 7.1 Required NGINX Configuration Pattern

Every FastAPI service exposed via NGINX must include documentation routes:

```nginx
# [Service Name] - [subdomain].example.com
# [Brief description of what this service does]
# API: [port], Frontend: [port] (if applicable)

upstream service_api {
    server 127.0.0.1:[port];
}

server {
    listen 443 ssl;
    server_name [subdomain].example.com;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/[cert-name]/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/[cert-name]/privkey.pem;

    # API endpoints
    location /api/ {
        proxy_pass http://service_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # API docs (Swagger UI)
    location /docs {
        proxy_pass http://service_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # ReDoc alternative docs
    location /redoc {
        proxy_pass http://service_api;
        proxy_set_header Host $host;
    }

    # OpenAPI spec
    location /openapi.json {
        proxy_pass http://service_api;
        proxy_set_header Host $host;
    }

    # Health check endpoint
    location = /health {
        proxy_pass http://service_api/api/v1/health;
        proxy_set_header Host $host;
    }
}
```

### 7.2 Required Header Comments

Every NGINX config file MUST include:

1. **Line 1**: Service name and domain
2. **Line 2**: Brief service description
3. **Line 3**: Port allocation (API and Frontend if applicable)

### 7.3 Verification Commands

```bash
# Check if /docs is accessible
curl -s -o /dev/null -w "%{http_code}" https://[site].example.com/docs

# Verify all documentation endpoints
for endpoint in docs redoc openapi.json; do
    echo -n "$endpoint: "
    curl -s -o /dev/null -w "%{http_code}" "https://[site].example.com/$endpoint"
    echo
done

# Test NGINX configuration
sudo nginx -t
sudo systemctl reload nginx
```

---

## Phase 8: Dependency Hygiene

### 8.1 Pin Dependencies Properly

If using `requirements.txt`:

```bash
# Generate pinned requirements from current environment
pip freeze > requirements.lock.txt

# Keep requirements.txt with flexible versions for development
# Keep requirements.lock.txt for reproducible deployments
```

If using `pyproject.toml`, use proper dependency groups:

```toml
[project]
dependencies = [
    "fastapi>=0.100",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "ruff>=0.4",
    "pytest>=8.0",
    "mypy>=1.10",
]
docs = [
    "mkdocs-material>=9.5",
    "mkdocstrings[python]>=0.25",
]
```

### 8.2 Remove Unused Dependencies

```bash
# Use deptry to find unused packages
pip install deptry
deptry .
```

---

## Phase 9: Testing & CI Hygiene

### 9.1 Test Organization

```
./tests/
├── __init__.py
├── conftest.py           # Shared fixtures
├── unit/                 # Fast, isolated tests
├── integration/          # Tests requiring external resources
└── fixtures/             # Test data files
```

### 9.2 Pytest Configuration

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = [
    "-ra",                 # Show summary of all non-passing tests
    "--strict-markers",    # Error on unknown markers
    "--strict-config",     # Error on config issues
]
filterwarnings = [
    "error",               # Treat warnings as errors
    "ignore::DeprecationWarning",
]
```

### 9.3 Pre-commit Hooks

Create/update `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.4  # Use latest
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: check-merge-conflict
```

Install hooks:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

---

## Phase 10: Final Verification

### 10.1 Checklist

Run through this checklist before completing:

- [ ] `ruff check .` passes with no errors
- [ ] `ruff format --check .` shows no changes needed
- [ ] `pytest` passes (if tests exist)
- [ ] `python -m py_compile <main_module>` succeeds
- [ ] No sensitive data (API keys, passwords) in committed files
- [ ] `.gitignore` is comprehensive
- [ ] `README.md` is current and accurate
- [ ] All imports resolve correctly
- [ ] `/docs` endpoint accessible (for FastAPI services)
- [ ] `/api/v1/health` returns healthy status

### 10.2 Generate Report

Create `./archive/maintenance-report-YYYY-MM-DD.md` documenting:

- Files archived (with reasons)
- Files deleted
- Major structural changes
- New configurations added
- Outstanding issues or TODOs for future cycles
- Dependency changes

---

## Commit Strategy

Make atomic commits as you complete each phase:

1. `chore: archive stale files and logs`
2. `docs: reorganize documentation structure`
3. `style: apply ruff formatting`
4. `refactor: add type hints to public API`
5. `chore: update project configuration`
6. `chore: add pre-commit hooks`

Use conventional commit prefixes: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

---

## Notes

- **Don't break things**: If unsure whether a file is used, check git blame and grep for imports before archiving
- **Preserve history**: Use `git mv` instead of `mv` + `git add` when moving files
- **Be conservative with deletions**: Archive first, delete in a future cycle after confirming nothing broke
- **Document decisions**: Leave a comment in the maintenance report explaining non-obvious choices
