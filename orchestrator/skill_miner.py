"""Mine skills from Claude Code conversation logs

Scans conversation logs to detect repeated multi-step workflows
that could be captured as reusable skills.
"""

import json
import logging
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from .models import SkillCandidate

logger = logging.getLogger(__name__)


# =============================================================================
# SKILL SIGNATURES - Patterns that indicate skill-worthy workflows
# =============================================================================

SKILL_SIGNATURES = {
    "release": {
        "description": "Version release workflow",
        "tool_patterns": [
            (r"Edit", r"pyproject\.toml|package\.json|Cargo\.toml"),
            (r"Edit", r"__init__\.py|version\.(py|ts|js)"),
            (r"Bash", r"git\s+(add|commit|tag|push)"),
        ],
        "text_patterns": [
            r"v?\d+\.\d+\.\d+",
            r"\b(release|bump|version)\b",
        ],
        "min_matches": 2,
    },
    "deploy": {
        "description": "Deployment workflow",
        "tool_patterns": [
            (r"Bash", r"(docker|kubectl|systemctl|pm2|supervisorctl)"),
            (r"Bash", r"(deploy|push|publish)"),
        ],
        "text_patterns": [
            r"\b(deploy|staging|production|release)\b",
            r"\b(build|test|verify)\b",
        ],
        "min_matches": 2,
    },
    "test": {
        "description": "Test execution workflow",
        "tool_patterns": [
            (r"Bash", r"(pytest|npm\s+test|cargo\s+test|go\s+test|jest)"),
        ],
        "text_patterns": [
            r"\b(run|execute)\s+(tests?|specs?)\b",
            r"\b(test|spec)\s+(pass|fail)",
        ],
        "min_matches": 1,
    },
    "format": {
        "description": "Code formatting workflow",
        "tool_patterns": [
            (r"Bash", r"(ruff|black|prettier|eslint|cargo\s+fmt)"),
            (r"Bash", r"git\s+(add|commit)"),
        ],
        "text_patterns": [
            r"\b(format|lint|style)\b",
            r"\b(cleanup|fix)\b",
        ],
        "min_matches": 2,
    },
    "maintenance": {
        "description": "Code maintenance workflow",
        "tool_patterns": [
            (r"Bash", r"(ruff|pytest|git)"),
            (r"Edit", r"\.(py|ts|js|rs)$"),
            (r"Bash", r"git\s+commit"),
        ],
        "text_patterns": [
            r"\b(maintenance|cleanup|refactor)\b",
            r"\b(archive|organize|structure)\b",
        ],
        "min_matches": 2,
    },
    "commit": {
        "description": "Git commit workflow",
        "tool_patterns": [
            (r"Bash", r"git\s+status"),
            (r"Bash", r"git\s+add"),
            (r"Bash", r"git\s+commit"),
        ],
        "text_patterns": [
            r"\b(commit|save|checkpoint)\b",
        ],
        "min_matches": 2,
    },
    "pr": {
        "description": "Pull request workflow",
        "tool_patterns": [
            (r"Bash", r"git\s+push"),
            (r"Bash", r"gh\s+pr"),
        ],
        "text_patterns": [
            r"\b(pr|pull\s*request|merge)\b",
            r"\b(review|approve)\b",
        ],
        "min_matches": 2,
    },
    "service": {
        "description": "Service management workflow",
        "tool_patterns": [
            (r"Bash", r"(systemctl|service|supervisorctl|pm2)"),
        ],
        "text_patterns": [
            r"\b(restart|start|stop|reload)\b",
            r"\b(service|daemon|process)\b",
        ],
        "min_matches": 1,
    },
}


class SkillMiner:
    """Mine skills from Claude Code conversation logs"""

    CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

    def __init__(
        self,
        project_filter: str | None = None,
        min_confidence: float = 0.5,
    ):
        self.project_filter = project_filter
        self.min_confidence = min_confidence

    def get_project_dirs(self) -> Iterator[Path]:
        """Yield project directories, optionally filtered"""
        if not self.CLAUDE_PROJECTS_DIR.exists():
            logger.warning(f"Projects directory not found: {self.CLAUDE_PROJECTS_DIR}")
            return

        for project_dir in self.CLAUDE_PROJECTS_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            if self.project_filter:
                if self.project_filter.lower() not in project_dir.name.lower():
                    continue
            yield project_dir

    def get_session_files(self, project_dir: Path) -> Iterator[Path]:
        """Yield JSONL session files from a project directory"""
        for jsonl_file in project_dir.glob("*.jsonl"):
            if jsonl_file.name.startswith("agent-"):
                continue
            yield jsonl_file

    def mine_all(self) -> Iterator[SkillCandidate]:
        """Mine all conversation logs for skill candidates"""
        for project_dir in self.get_project_dirs():
            for session_file in self.get_session_files(project_dir):
                try:
                    yield from self.mine_session(session_file)
                except Exception as e:
                    logger.error(f"Error mining {session_file}: {e}")

    def mine_session(self, session_file: Path) -> Iterator[SkillCandidate]:
        """Mine a single session file for skill candidates"""
        messages = self._load_messages(session_file)
        if not messages:
            return

        # Extract tool call sequences
        tool_calls = self._extract_tool_calls(messages)
        if not tool_calls:
            return

        # Extract user inputs that triggered workflows
        user_inputs = self._extract_user_inputs(messages)

        # Match against skill signatures
        for skill_type, signature in SKILL_SIGNATURES.items():
            confidence = self._calculate_match_confidence(
                tool_calls, user_inputs, signature
            )

            if confidence >= self.min_confidence:
                yield SkillCandidate(
                    skill_type=skill_type,
                    session_file=str(session_file),
                    tool_sequence=self._extract_matching_tools(tool_calls, signature),
                    user_input=self._find_trigger_input(user_inputs, signature),
                    confidence=confidence,
                    suggested_name=f"{skill_type}_{session_file.stem[:8]}",
                    suggested_triggers=self._generate_triggers(user_inputs, signature),
                )

    def _load_messages(self, session_file: Path) -> list[dict]:
        """Load messages from a JSONL session file"""
        messages = []
        with session_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return messages

    def _extract_tool_calls(self, messages: list[dict]) -> list[tuple[str, str]]:
        """Extract (tool_name, tool_input) pairs from messages"""
        tool_calls = []

        for msg in messages:
            if msg.get("type") != "assistant":
                continue

            content = msg.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use":
                    continue

                tool_name = block.get("name", "")
                tool_input = json.dumps(block.get("input", {}))
                tool_calls.append((tool_name, tool_input))

        return tool_calls

    def _extract_user_inputs(self, messages: list[dict]) -> list[str]:
        """Extract user input text from messages"""
        inputs = []

        for msg in messages:
            if msg.get("type") != "user":
                continue

            content = msg.get("message", {}).get("content", "")
            if isinstance(content, str) and content.strip():
                inputs.append(content.strip())
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text:
                            inputs.append(text)

        return inputs

    def _calculate_match_confidence(
        self,
        tool_calls: list[tuple[str, str]],
        user_inputs: list[str],
        signature: dict,
    ) -> float:
        """Calculate how well tool calls match a skill signature"""
        tool_patterns = signature["tool_patterns"]
        text_patterns = signature["text_patterns"]
        min_matches = signature["min_matches"]

        # Count tool pattern matches
        tool_matches = 0
        for tool_name, tool_input in tool_calls:
            for name_pattern, input_pattern in tool_patterns:
                if re.search(name_pattern, tool_name, re.IGNORECASE):
                    if re.search(input_pattern, tool_input, re.IGNORECASE):
                        tool_matches += 1
                        break

        # Count text pattern matches in user inputs
        text_matches = 0
        combined_text = " ".join(user_inputs).lower()
        for pattern in text_patterns:
            if re.search(pattern, combined_text, re.IGNORECASE):
                text_matches += 1

        # Calculate confidence
        total_patterns = len(tool_patterns) + len(text_patterns)
        total_matches = tool_matches + text_matches

        if total_matches < min_matches:
            return 0.0

        confidence = total_matches / total_patterns
        return min(confidence, 1.0)

    def _extract_matching_tools(
        self, tool_calls: list[tuple[str, str]], signature: dict
    ) -> list[tuple[str, str]]:
        """Extract tool calls that match the signature"""
        matching = []
        for tool_name, tool_input in tool_calls:
            for name_pattern, input_pattern in signature["tool_patterns"]:
                if re.search(name_pattern, tool_name, re.IGNORECASE):
                    if re.search(input_pattern, tool_input, re.IGNORECASE):
                        # Simplify the input for display
                        simplified = (
                            tool_input[:100] + "..."
                            if len(tool_input) > 100
                            else tool_input
                        )
                        matching.append((tool_name, simplified))
                        break
        return matching

    def _find_trigger_input(self, user_inputs: list[str], signature: dict) -> str:
        """Find the user input that likely triggered this workflow"""
        text_patterns = signature["text_patterns"]

        for user_input in user_inputs:
            for pattern in text_patterns:
                if re.search(pattern, user_input, re.IGNORECASE):
                    return user_input

        return user_inputs[0] if user_inputs else ""

    def _generate_triggers(self, user_inputs: list[str], signature: dict) -> list[str]:
        """Generate suggested trigger patterns from user inputs"""
        triggers = []
        text_patterns = signature["text_patterns"]

        for user_input in user_inputs[:5]:  # Limit to first 5
            for pattern in text_patterns:
                if re.search(pattern, user_input, re.IGNORECASE):
                    # Normalize the trigger
                    trigger = user_input.lower().strip()
                    trigger = re.sub(r"\s+", " ", trigger)
                    if len(trigger) < 100:
                        triggers.append(trigger)
                    break

        return list(set(triggers))[:3]  # Dedupe and limit


def aggregate_candidates(
    candidates: list[SkillCandidate],
) -> dict[str, list[SkillCandidate]]:
    """Group skill candidates by type and sort by confidence"""
    grouped: dict[str, list[SkillCandidate]] = {}

    for candidate in candidates:
        if candidate.skill_type not in grouped:
            grouped[candidate.skill_type] = []
        grouped[candidate.skill_type].append(candidate)

    # Sort each group by confidence
    for type_candidates in grouped.values():
        type_candidates.sort(key=lambda c: c.confidence, reverse=True)

    return grouped


def summarize_mining_results(candidates: list[SkillCandidate]) -> dict:
    """Summarize mining results for display"""
    grouped = aggregate_candidates(candidates)

    summary = {
        "total_candidates": len(candidates),
        "by_type": {},
    }

    for skill_type, type_candidates in grouped.items():
        summary["by_type"][skill_type] = {
            "count": len(type_candidates),
            "avg_confidence": sum(c.confidence for c in type_candidates)
            / len(type_candidates),
            "top_triggers": [],
        }

        # Collect unique triggers
        all_triggers: Counter = Counter()
        for c in type_candidates:
            for t in c.suggested_triggers:
                all_triggers[t] += 1

        summary["by_type"][skill_type]["top_triggers"] = [
            t for t, _ in all_triggers.most_common(5)
        ]

    return summary
