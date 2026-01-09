#!/usr/bin/env python3
"""
Extract Claude Code conversations from ~/.claude/projects for training data generation.

This script parses JSONL conversation logs and outputs structured training data
in various formats suitable for fine-tuning or analysis.

Usage:
    python scripts/extract_conversations.py [OPTIONS]

Examples:
    # Extract all conversations to JSONL
    python scripts/extract_conversations.py --output training_data.jsonl

    # Extract from specific project
    python scripts/extract_conversations.py --project cbos --output cbos_training.jsonl

    # Export as conversation pairs (user/assistant)
    python scripts/extract_conversations.py --format pairs --output pairs.jsonl

    # Include thinking blocks
    python scripts/extract_conversations.py --include-thinking --output with_thinking.jsonl

    # Filter by date range
    python scripts/extract_conversations.py --after 2025-01-01 --before 2025-02-01
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional
from enum import Enum


class OutputFormat(Enum):
    JSONL = "jsonl"           # One message per line
    PAIRS = "pairs"           # User/assistant conversation pairs
    CONVERSATIONS = "conversations"  # Full conversation threads
    SHAREGPT = "sharegpt"     # ShareGPT format for training


@dataclass
class ToolUse:
    """Represents a tool invocation by the assistant."""
    tool_name: str
    tool_id: str
    input_data: dict


@dataclass
class Message:
    """A single message in a conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: str
    uuid: str
    session_id: str
    project: str
    cwd: str
    thinking: Optional[str] = None
    tool_uses: list[ToolUse] = field(default_factory=list)
    model: Optional[str] = None
    parent_uuid: Optional[str] = None
    is_sidechain: bool = False


@dataclass
class ConversationPair:
    """A user message paired with assistant response."""
    user_message: str
    assistant_response: str
    thinking: Optional[str] = None
    tool_uses: list[dict] = field(default_factory=list)
    project: str = ""
    session_id: str = ""
    timestamp: str = ""


@dataclass
class Conversation:
    """A full conversation thread."""
    session_id: str
    project: str
    messages: list[Message]
    summary: Optional[str] = None


class ConversationExtractor:
    """Extract and process Claude Code conversation logs."""

    CLAUDE_DIR = Path.home() / ".claude"
    PROJECTS_DIR = CLAUDE_DIR / "projects"

    def __init__(
        self,
        include_thinking: bool = False,
        include_tool_uses: bool = True,
        include_sidechains: bool = False,
        project_filter: Optional[str] = None,
        after_date: Optional[datetime] = None,
        before_date: Optional[datetime] = None,
    ):
        self.include_thinking = include_thinking
        self.include_tool_uses = include_tool_uses
        self.include_sidechains = include_sidechains
        self.project_filter = project_filter
        self.after_date = after_date
        self.before_date = before_date

    def get_project_dirs(self) -> Iterator[Path]:
        """Yield project directories, optionally filtered."""
        if not self.PROJECTS_DIR.exists():
            return

        for project_dir in self.PROJECTS_DIR.iterdir():
            if not project_dir.is_dir():
                continue

            # Apply project filter if specified
            if self.project_filter:
                if self.project_filter.lower() not in project_dir.name.lower():
                    continue

            yield project_dir

    def get_session_files(self, project_dir: Path) -> Iterator[Path]:
        """Yield JSONL session files from a project directory."""
        for jsonl_file in project_dir.glob("*.jsonl"):
            # Skip agent files (subagent logs)
            if jsonl_file.name.startswith("agent-"):
                continue
            yield jsonl_file

    def parse_timestamp(self, ts: str) -> Optional[datetime]:
        """Parse ISO timestamp string."""
        try:
            # Handle various timestamp formats
            ts = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return None

    def is_in_date_range(self, timestamp: str) -> bool:
        """Check if timestamp falls within configured date range."""
        dt = self.parse_timestamp(timestamp)
        if not dt:
            return True  # Include if we can't parse

        if self.after_date and dt < self.after_date:
            return False
        if self.before_date and dt > self.before_date:
            return False
        return True

    def extract_tool_uses(self, content: list) -> list[ToolUse]:
        """Extract tool use blocks from assistant message content."""
        tool_uses = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_uses.append(ToolUse(
                    tool_name=block.get("name", "unknown"),
                    tool_id=block.get("id", ""),
                    input_data=block.get("input", {})
                ))
        return tool_uses

    def extract_thinking(self, content: list) -> Optional[str]:
        """Extract thinking block from assistant message content."""
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                return block.get("thinking", "")
        return None

    def extract_text(self, content) -> str:
        """Extract text content from message."""
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            return "\n".join(text_parts)

        return str(content)

    def parse_message(self, line: dict, project_path: str) -> Optional[Message]:
        """Parse a JSONL line into a Message object."""
        msg_type = line.get("type")

        # Only process user and assistant messages
        if msg_type not in ("user", "assistant"):
            return None

        # Skip sidechains if not included
        if line.get("isSidechain") and not self.include_sidechains:
            return None

        message_data = line.get("message", {})
        timestamp = line.get("timestamp", "")

        # Apply date filter
        if not self.is_in_date_range(timestamp):
            return None

        role = message_data.get("role", msg_type)
        content = message_data.get("content", "")

        # Extract components
        text_content = self.extract_text(content)
        thinking = None
        tool_uses = []

        if role == "assistant" and isinstance(content, list):
            if self.include_thinking:
                thinking = self.extract_thinking(content)
            if self.include_tool_uses:
                tool_uses = self.extract_tool_uses(content)

        return Message(
            role=role,
            content=text_content,
            timestamp=timestamp,
            uuid=line.get("uuid", ""),
            session_id=line.get("sessionId", ""),
            project=project_path,
            cwd=line.get("cwd", ""),
            thinking=thinking,
            tool_uses=tool_uses,
            model=message_data.get("model"),
            parent_uuid=line.get("parentUuid"),
            is_sidechain=line.get("isSidechain", False),
        )

    def extract_messages(self) -> Iterator[Message]:
        """Extract all messages from all projects."""
        for project_dir in self.get_project_dirs():
            project_path = project_dir.name.replace("-", "/").lstrip("/")

            for session_file in self.get_session_files(project_dir):
                try:
                    with open(session_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                                message = self.parse_message(data, project_path)
                                if message:
                                    yield message
                            except json.JSONDecodeError:
                                continue
                except (IOError, OSError) as e:
                    print(f"Warning: Could not read {session_file}: {e}", file=sys.stderr)

    def extract_pairs(self) -> Iterator[ConversationPair]:
        """Extract user/assistant message pairs."""
        messages = list(self.extract_messages())

        # Group by session and sort by timestamp
        sessions: dict[str, list[Message]] = {}
        for msg in messages:
            key = f"{msg.project}:{msg.session_id}"
            if key not in sessions:
                sessions[key] = []
            sessions[key].append(msg)

        for session_key, session_msgs in sessions.items():
            # Sort by timestamp
            session_msgs.sort(key=lambda m: m.timestamp)

            # Pair user messages with following assistant response
            i = 0
            while i < len(session_msgs):
                if session_msgs[i].role == "user":
                    user_msg = session_msgs[i]

                    # Collect all assistant responses until next user message
                    assistant_parts = []
                    thinking = None
                    tool_uses = []
                    j = i + 1

                    while j < len(session_msgs) and session_msgs[j].role == "assistant":
                        assistant_parts.append(session_msgs[j].content)
                        if session_msgs[j].thinking:
                            thinking = session_msgs[j].thinking
                        tool_uses.extend([asdict(t) for t in session_msgs[j].tool_uses])
                        j += 1

                    if assistant_parts:
                        yield ConversationPair(
                            user_message=user_msg.content,
                            assistant_response="\n".join(filter(None, assistant_parts)),
                            thinking=thinking,
                            tool_uses=tool_uses,
                            project=user_msg.project,
                            session_id=user_msg.session_id,
                            timestamp=user_msg.timestamp,
                        )

                    i = j
                else:
                    i += 1

    def extract_conversations(self) -> Iterator[Conversation]:
        """Extract full conversation threads."""
        messages = list(self.extract_messages())

        # Group by session
        sessions: dict[str, list[Message]] = {}
        for msg in messages:
            key = f"{msg.project}:{msg.session_id}"
            if key not in sessions:
                sessions[key] = []
            sessions[key].append(msg)

        for session_key, session_msgs in sessions.items():
            if not session_msgs:
                continue

            # Sort by timestamp
            session_msgs.sort(key=lambda m: m.timestamp)

            yield Conversation(
                session_id=session_msgs[0].session_id,
                project=session_msgs[0].project,
                messages=session_msgs,
            )

    def to_sharegpt_format(self, pair: ConversationPair) -> dict:
        """Convert a conversation pair to ShareGPT format."""
        conversations = [
            {"from": "human", "value": pair.user_message},
            {"from": "gpt", "value": pair.assistant_response},
        ]

        return {
            "conversations": conversations,
            "source": f"claude-code:{pair.project}",
            "metadata": {
                "session_id": pair.session_id,
                "timestamp": pair.timestamp,
                "has_thinking": pair.thinking is not None,
                "tool_count": len(pair.tool_uses),
            }
        }


def message_to_dict(msg: Message) -> dict:
    """Convert Message to serializable dict."""
    return {
        "role": msg.role,
        "content": msg.content,
        "timestamp": msg.timestamp,
        "uuid": msg.uuid,
        "session_id": msg.session_id,
        "project": msg.project,
        "cwd": msg.cwd,
        "thinking": msg.thinking,
        "tool_uses": [asdict(t) for t in msg.tool_uses],
        "model": msg.model,
        "parent_uuid": msg.parent_uuid,
        "is_sidechain": msg.is_sidechain,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Extract Claude Code conversations for training data generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "-o", "--output",
        type=str,
        default="-",
        help="Output file (default: stdout)"
    )

    parser.add_argument(
        "-f", "--format",
        type=str,
        choices=["jsonl", "pairs", "conversations", "sharegpt"],
        default="jsonl",
        help="Output format (default: jsonl)"
    )

    parser.add_argument(
        "-p", "--project",
        type=str,
        help="Filter by project name (substring match)"
    )

    parser.add_argument(
        "--include-thinking",
        action="store_true",
        help="Include Claude's thinking blocks"
    )

    parser.add_argument(
        "--include-sidechains",
        action="store_true",
        help="Include sidechain (branched) conversations"
    )

    parser.add_argument(
        "--no-tool-uses",
        action="store_true",
        help="Exclude tool use information"
    )

    parser.add_argument(
        "--after",
        type=str,
        help="Only include messages after this date (YYYY-MM-DD)"
    )

    parser.add_argument(
        "--before",
        type=str,
        help="Only include messages before this date (YYYY-MM-DD)"
    )

    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print statistics instead of extracting"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    # Parse dates
    after_date = None
    before_date = None
    if args.after:
        after_date = datetime.fromisoformat(args.after)
    if args.before:
        before_date = datetime.fromisoformat(args.before)

    # Create extractor
    extractor = ConversationExtractor(
        include_thinking=args.include_thinking,
        include_tool_uses=not args.no_tool_uses,
        include_sidechains=args.include_sidechains,
        project_filter=args.project,
        after_date=after_date,
        before_date=before_date,
    )

    # Stats mode
    if args.stats:
        print_stats(extractor, args.verbose)
        return

    # Open output
    if args.output == "-":
        out_file = sys.stdout
    else:
        out_file = open(args.output, "w", encoding="utf-8")

    try:
        if args.format == "jsonl":
            for msg in extractor.extract_messages():
                json.dump(message_to_dict(msg), out_file)
                out_file.write("\n")

        elif args.format == "pairs":
            for pair in extractor.extract_pairs():
                json.dump(asdict(pair), out_file)
                out_file.write("\n")

        elif args.format == "conversations":
            for conv in extractor.extract_conversations():
                data = {
                    "session_id": conv.session_id,
                    "project": conv.project,
                    "messages": [message_to_dict(m) for m in conv.messages],
                    "summary": conv.summary,
                }
                json.dump(data, out_file)
                out_file.write("\n")

        elif args.format == "sharegpt":
            for pair in extractor.extract_pairs():
                json.dump(extractor.to_sharegpt_format(pair), out_file)
                out_file.write("\n")

    finally:
        if args.output != "-":
            out_file.close()


def print_stats(extractor: ConversationExtractor, verbose: bool = False):
    """Print statistics about available conversation data."""
    from collections import Counter

    project_counts = Counter()
    message_counts = {"user": 0, "assistant": 0}
    tool_counts = Counter()
    total_thinking = 0
    date_range = {"min": None, "max": None}

    for msg in extractor.extract_messages():
        project_counts[msg.project] += 1
        message_counts[msg.role] += 1

        if msg.thinking:
            total_thinking += 1

        for tool in msg.tool_uses:
            tool_counts[tool.tool_name] += 1

        if msg.timestamp:
            ts = extractor.parse_timestamp(msg.timestamp)
            if ts:
                if date_range["min"] is None or ts < date_range["min"]:
                    date_range["min"] = ts
                if date_range["max"] is None or ts > date_range["max"]:
                    date_range["max"] = ts

    print("=== Claude Code Conversation Statistics ===\n")

    print(f"Total Messages: {sum(message_counts.values())}")
    print(f"  User:      {message_counts['user']}")
    print(f"  Assistant: {message_counts['assistant']}")
    print(f"  With Thinking: {total_thinking}")
    print()

    print(f"Projects: {len(project_counts)}")
    if verbose:
        for project, count in project_counts.most_common(20):
            print(f"  {project}: {count}")
    print()

    print(f"Tool Uses: {sum(tool_counts.values())}")
    if tool_counts:
        for tool, count in tool_counts.most_common(15):
            print(f"  {tool}: {count}")
    print()

    if date_range["min"] and date_range["max"]:
        print(f"Date Range: {date_range['min'].date()} to {date_range['max'].date()}")


if __name__ == "__main__":
    main()
