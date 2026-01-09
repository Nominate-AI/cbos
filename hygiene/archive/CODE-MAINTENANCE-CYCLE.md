
## Python Project Maintenance Cycle

```markdown
# Python 3.1x Project Maintenance Cycle

You are running a comprehensive maintenance cycle on this Python project. Work systematically through each phase, committing logical chunks as you go. Ask clarifying questions only if you encounter blocking ambiguities.

## Phase 1: Reconnaissance

Before making changes, analyze the project:

1. **Map the current structure** - Run `tree -I '__pycache__|*.pyc|.git|.venv|venv|node_modules' -L 3` or equivalent
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

### 2.3 Purge (Delete, Don’t Archive)

- `__pycache__/` directories
- `.pyc`, `.pyo` files
- `.coverage`, `htmlcov/`
- `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`
- `*.DS_Store`, `Thumbs.db`
- Empty `__init__.py` files in non-package directories

### 2.4 Update .gitignore

Ensure `.gitignore` includes standard Python ignores. Use GitHub’s Python template as baseline.

-----

## Phase 3: Documentation Organization

### 3.1 Create Docs Structure

```
./docs/
├── index.md              # Project overview (auto-generate if missing)
├── getting-started.md    # Installation & quickstart
├── api/                  # API reference (mkdocstrings will populate)
├── guides/               # How-to guides, tutorials
├── reference/            # Technical reference, architecture
├── contributing.md       # Contribution guidelines
└── changelog.md          # Version history
```

### 3.2 Consolidate Documentation

- Move all `.md` files from project root (except `README.md`) into appropriate `docs/` subdirectory
- Convert any `.rst` files to Markdown if the project uses mkdocs
- Move `CHANGELOG.md`, `HISTORY.md`, `CHANGES.md` → `docs/changelog.md`
- Move `CONTRIBUTING.md` → `docs/contributing.md`
- Consolidate duplicate docs (e.g., multiple READMEs in subdirectories)

### 3.3 README.md Hygiene

Ensure `README.md` in project root contains:

- Project name and one-line description
- Badges (if applicable): CI status, PyPI version, Python versions
- Installation instructions
- Minimal usage example
- Link to full documentation

-----

## Phase 4: Code Formatting & Style

### 4.1 Tooling Setup (Ruff-first approach)

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

### 4.2 Run Formatting

```bash
# Format all Python files
ruff format .

# Fix auto-fixable lint issues
ruff check --fix .

# Show remaining issues
ruff check .
```

### 4.3 Type Hints Hygiene

- Add type hints to all public function signatures (parameters and return types)
- Use modern syntax: `list[str]` not `List[str]`, `str | None` not `Optional[str]`
- Add `py.typed` marker file if this is a library intended for distribution

-----

## Phase 5: Docstrings & Comments

### 5.1 Docstring Standard

Use **Google-style docstrings** (mkdocstrings default, most readable):

```python
def process_voter(voter_id: str, include_history: bool = False) -> VoterRecord:
    """Retrieve and process a voter record from the database.

    Fetches the voter record, validates required fields, and optionally
    enriches with voting history data.

    Args:
        voter_id: Unique identifier for the voter (SVID format).
        include_history: Whether to include voting history. Defaults to False.

    Returns:
        Processed voter record with validated fields.

    Raises:
        VoterNotFoundError: If no voter exists with the given ID.
        ValidationError: If required fields are missing or malformed.

    Example:
        >>> voter = process_voter("MI-12345", include_history=True)
        >>> print(voter.name)
        'Jane Doe'
    """
```

### 5.2 Docstring Coverage

Ensure docstrings exist for:

- All public modules (top of file)
- All public classes (below class definition)
- All public functions and methods
- Complex private functions (prefix with `_`)

### 5.3 Comment Cleanup

- Remove commented-out code (Ruff’s ERA rule catches this)
- Convert `# TODO` comments to GitHub Issues where appropriate
- Remove obvious/redundant comments (`# increment counter` above `counter += 1`)
- Keep comments that explain *why*, remove those that explain *what*

-----

## Phase 6: Dependency Hygiene

### 6.1 Pin Dependencies Properly

If using `requirements.txt`:

```bash
# Generate pinned requirements from current environment
pip freeze > requirements.lock.txt

# Keep requirements.txt with flexible versions for development
# Keep requirements.lock.txt for reproducible deployments
```

If using `pyproject.toml` with pip, consider migrating to proper dependency groups:

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

### 6.2 Remove Unused Dependencies

```bash
# Use pip-autoremove or deptry to find unused packages
pip install deptry
deptry .
```

-----

## Phase 7: Testing & CI Hygiene

### 7.1 Test Organization

```
./tests/
├── __init__.py
├── conftest.py           # Shared fixtures
├── unit/                 # Fast, isolated tests
├── integration/          # Tests requiring external resources
└── fixtures/             # Test data files
```

### 7.2 Pytest Configuration

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

### 7.3 Pre-commit Hooks

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

-----

## Phase 8: Final Verification

### 8.1 Checklist

Run through this checklist before completing:

- [ ] `ruff check .` passes with no errors
- [ ] `ruff format --check .` shows no changes needed
- [ ] `pytest` passes (if tests exist)
- [ ] `python -m py_compile <main_module>` succeeds
- [ ] No sensitive data (API keys, passwords) in committed files
- [ ] `.gitignore` is comprehensive
- [ ] `README.md` is current and accurate
- [ ] All imports resolve correctly

### 8.2 Generate Report

Create `./archive/maintenance-report-YYYY-MM-DD.md` documenting:

- Files archived (with reasons)
- Files deleted
- Major structural changes
- New configurations added
- Outstanding issues or TODOs for future cycles
- Dependency changes

-----

## Commit Strategy

Make atomic commits as you complete each phase:

1. `chore: archive stale files and logs`
2. `docs: reorganize documentation structure`
3. `style: apply ruff formatting`
4. `refactor: add type hints to public API`
5. `chore: update project configuration`
6. `chore: add pre-commit hooks`

Use conventional commit prefixes: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

-----

## Notes

- **Don’t break things**: If unsure whether a file is used, check git blame and grep for imports before archiving
- **Preserve history**: Use `git mv` instead of `mv` + `git add` when moving files
- **Be conservative with deletions**: Archive first, delete in a future cycle after confirming nothing broke
- **Document decisions**: Leave a comment in the maintenance report explaining non-obvious choices
