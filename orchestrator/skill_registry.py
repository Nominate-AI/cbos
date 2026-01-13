"""Skill registry for loading and managing skill definitions

Loads skills from YAML files in:
1. Built-in skills: orchestrator/skills/
2. Global user skills: ~/.cbos/skills/
3. Project skills: .cbos/skills/
"""

import logging
from pathlib import Path

import yaml

from .models import ParameterType
from .models import Skill
from .models import SkillCondition
from .models import SkillParameter
from .models import SkillStep
from .models import SkillTrigger
from .models import StepType

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Registry for loading and managing skills"""

    def __init__(
        self,
        builtin_dir: Path | None = None,
        user_dir: Path | None = None,
        project_dir: Path | None = None,
    ):
        # Built-in skills shipped with orchestrator
        self.builtin_dir = builtin_dir or Path(__file__).parent / "skills"
        # User's global skills
        self.user_dir = user_dir or Path.home() / ".cbos" / "skills"
        # Project-specific skills (set when loading for a specific project)
        self.project_dir = project_dir

        self._skills: dict[str, Skill] = {}
        self._loaded = False

    def load_all(self, project_path: Path | None = None) -> int:
        """Load all skills from all sources

        Args:
            project_path: Optional project path to load project-specific skills

        Returns:
            Number of skills loaded
        """
        self._skills.clear()

        # Load built-in skills first
        loaded = self._load_from_directory(self.builtin_dir, source="builtin")

        # Load user's global skills (can override built-in)
        loaded += self._load_from_directory(self.user_dir, source="user")

        # Load project-specific skills (highest priority)
        if project_path:
            project_skills_dir = project_path / ".cbos" / "skills"
            loaded += self._load_from_directory(project_skills_dir, source="project")

        self._loaded = True
        logger.info(f"Loaded {len(self._skills)} skills ({loaded} files)")
        return loaded

    def _load_from_directory(self, directory: Path, source: str) -> int:
        """Load skills from a directory

        Args:
            directory: Directory containing YAML skill files
            source: Source identifier for logging

        Returns:
            Number of files loaded
        """
        if not directory.exists():
            return 0

        loaded = 0
        for yaml_file in directory.glob("*.yaml"):
            try:
                skill = self._load_skill_file(yaml_file)
                if skill:
                    self._skills[skill.name] = skill
                    loaded += 1
                    logger.debug(
                        f"Loaded skill '{skill.name}' from {source}: {yaml_file}"
                    )
            except Exception as e:
                logger.error(f"Failed to load skill from {yaml_file}: {e}")

        return loaded

    def _load_skill_file(self, path: Path) -> Skill | None:
        """Load a single skill from a YAML file"""
        with path.open() as f:
            data = yaml.safe_load(f)

        if not data or not isinstance(data, dict):
            return None

        # Parse triggers
        triggers = []
        for t in data.get("triggers", []):
            triggers.append(
                SkillTrigger(
                    pattern=t.get("pattern", ""),
                    confidence=t.get("confidence", 0.8),
                )
            )

        # Parse parameters
        parameters = []
        for p in data.get("parameters", []):
            param_type = p.get("type", "string")
            try:
                param_type_enum = ParameterType(param_type)
            except ValueError:
                param_type_enum = ParameterType.STRING

            parameters.append(
                SkillParameter(
                    name=p.get("name", ""),
                    type=param_type_enum,
                    description=p.get("description", ""),
                    required=p.get("required", True),
                    default=p.get("default"),
                    choices=p.get("choices"),
                )
            )

        # Parse preconditions
        preconditions = []
        for c in data.get("preconditions", []):
            preconditions.append(
                SkillCondition(
                    command=c.get("command", ""),
                    expect=c.get("expect"),
                    expect_exit=c.get("expect_exit"),
                    message=c.get("message", ""),
                )
            )

        # Parse steps
        steps = []
        for s in data.get("steps", []):
            step_type = s.get("type", "bash")
            try:
                step_type_enum = StepType(step_type)
            except ValueError:
                step_type_enum = StepType.BASH

            steps.append(
                SkillStep(
                    name=s.get("name", ""),
                    type=step_type_enum,
                    description=s.get("description", ""),
                    command=s.get("command"),
                    expect_exit=s.get("expect_exit"),
                    file=s.get("file"),
                    pattern=s.get("pattern"),
                    replacement=s.get("replacement"),
                    message=s.get("message"),
                    condition=s.get("condition"),
                    then_steps=s.get("then_steps"),
                    else_steps=s.get("else_steps"),
                )
            )

        # Parse postconditions
        postconditions = []
        for c in data.get("postconditions", []):
            postconditions.append(
                SkillCondition(
                    command=c.get("command", ""),
                    expect=c.get("expect"),
                    expect_exit=c.get("expect_exit"),
                    message=c.get("message", ""),
                )
            )

        return Skill(
            name=data.get("name", path.stem),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            triggers=triggers,
            parameters=parameters,
            preconditions=preconditions,
            steps=steps,
            postconditions=postconditions,
            project_scope=data.get("project_scope"),
            author=data.get("author"),
        )

    def get(self, name: str) -> Skill | None:
        """Get a skill by name"""
        if not self._loaded:
            self.load_all()
        return self._skills.get(name)

    def list_skills(self) -> list[Skill]:
        """List all loaded skills"""
        if not self._loaded:
            self.load_all()
        return list(self._skills.values())

    def list_names(self) -> list[str]:
        """List all skill names"""
        if not self._loaded:
            self.load_all()
        return list(self._skills.keys())

    def find_by_trigger(self, text: str) -> list[tuple[Skill, SkillTrigger, float]]:
        """Find skills that match a trigger pattern

        Args:
            text: User input text to match

        Returns:
            List of (skill, trigger, confidence) tuples, sorted by confidence
        """
        import re

        if not self._loaded:
            self.load_all()

        matches = []
        text_lower = text.lower()

        for skill in self._skills.values():
            for trigger in skill.triggers:
                # Convert pattern placeholders to regex
                # {param} -> (?P<param>.+?) with $ anchor for proper matching
                pattern = trigger.pattern.lower()
                # Escape regex special chars except our placeholders
                pattern = re.sub(r"([.^$*+?{}\\|()[\]])", r"\\\1", pattern)
                pattern = re.sub(r"\\{(\w+)\\}", r"(?P<\1>.+?)", pattern)
                # Anchor to end so non-greedy still captures full words
                pattern = pattern + "$"

                try:
                    match = re.search(pattern, text_lower)
                    if match:
                        matches.append((skill, trigger, trigger.confidence))
                except re.error:
                    # Invalid regex, try simple contains
                    clean_pattern = re.sub(r"\{(\w+)\}", r".*", trigger.pattern.lower())
                    if re.search(clean_pattern, text_lower):
                        matches.append((skill, trigger, trigger.confidence * 0.8))

        # Sort by confidence descending
        matches.sort(key=lambda x: x[2], reverse=True)
        return matches

    def extract_params(
        self, skill: Skill, trigger: SkillTrigger, text: str
    ) -> dict[str, str]:
        """Extract parameter values from matched text

        Args:
            skill: The matched skill
            trigger: The matched trigger
            text: The original user input

        Returns:
            Dict of parameter name -> extracted value
        """
        import re

        params = {}
        text_lower = text.lower()

        # Convert pattern to regex with named groups
        pattern = trigger.pattern.lower()
        # Escape regex special chars except our placeholders
        pattern = re.sub(r"([.^$*+?{}\\|()[\]])", r"\\\1", pattern)
        pattern = re.sub(r"\\{(\w+)\\}", r"(?P<\1>.+?)", pattern)
        # Anchor to end so non-greedy still captures full words
        pattern = pattern + "$"

        try:
            match = re.search(pattern, text_lower)
            if match:
                params = match.groupdict()
        except re.error:
            pass

        # Fill in defaults for missing params
        for param in skill.parameters:
            if param.name not in params and param.default:
                params[param.name] = param.default

        return params

    def to_dict(self, skill: Skill) -> dict:
        """Convert a skill to a dictionary for display/export"""
        return {
            "name": skill.name,
            "version": skill.version,
            "description": skill.description,
            "triggers": [
                {"pattern": t.pattern, "confidence": t.confidence}
                for t in skill.triggers
            ],
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type.value,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                }
                for p in skill.parameters
            ],
            "steps": [
                {"name": s.name, "type": s.type.value, "description": s.description}
                for s in skill.steps
            ],
        }


# Global registry instance
_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    """Get the global skill registry"""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry
