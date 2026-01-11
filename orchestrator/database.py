"""SQLite database management for pattern storage"""

import json
import logging
import sqlite3
import struct
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import settings
from .models import DecisionPattern, QuestionOption, QuestionType

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    session_id TEXT NOT NULL,
    tool_use_id TEXT NOT NULL UNIQUE,
    question_text TEXT NOT NULL,
    question_header TEXT,
    question_type TEXT,
    options_json TEXT,
    context_before TEXT,
    thinking TEXT,
    user_answer TEXT NOT NULL,
    is_selected_option INTEGER DEFAULT 0,
    timestamp TEXT NOT NULL,
    extracted_at TEXT NOT NULL
);
-- Note: Embeddings are stored in vectl (vectors.bin), not in SQLite

CREATE INDEX IF NOT EXISTS idx_patterns_type ON patterns(question_type);
CREATE INDEX IF NOT EXISTS idx_patterns_project ON patterns(project);
CREATE INDEX IF NOT EXISTS idx_patterns_timestamp ON patterns(timestamp);
"""


# Note: Embedding functions removed - embeddings are now stored in vectl


class PatternDatabase:
    """SQLite database for pattern storage"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.pattern_db_path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        """Initialize database connection and create schema"""
        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        logger.info(f"Connected to pattern database: {self.db_path}")

    def close(self) -> None:
        """Close database connection"""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Get active connection, connecting if needed"""
        if self._conn is None:
            self.connect()
        return self._conn

    def insert_pattern(
        self, pattern: DecisionPattern, embedding: Optional[list[float]] = None
    ) -> int:
        """Insert a pattern into the database, returns pattern ID.

        Note: embedding parameter is ignored - embeddings are stored in vectl.
        """
        options_json = json.dumps([opt.model_dump() for opt in pattern.options])

        cursor = self.conn.execute(
            """
            INSERT OR REPLACE INTO patterns (
                project, session_id, tool_use_id, question_text, question_header,
                question_type, options_json, context_before, thinking, user_answer,
                is_selected_option, timestamp, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pattern.project,
                pattern.session_id,
                pattern.tool_use_id,
                pattern.question_text,
                pattern.question_header,
                pattern.question_type.value,
                options_json,
                pattern.context_before,
                pattern.thinking,
                pattern.user_answer,
                1 if pattern.is_selected_option else 0,
                pattern.timestamp.isoformat(),
                pattern.extracted_at.isoformat(),
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_pattern(self, pattern_id: int) -> Optional[DecisionPattern]:
        """Get a pattern by ID"""
        row = self.conn.execute(
            "SELECT * FROM patterns WHERE id = ?", (pattern_id,)
        ).fetchone()
        return self._row_to_pattern(row) if row else None

    def get_all_patterns(self) -> list[DecisionPattern]:
        """Get all patterns"""
        rows = self.conn.execute("SELECT * FROM patterns").fetchall()
        return [self._row_to_pattern(row) for row in rows]

    def search_text(self, query: str, limit: int = 20) -> list[DecisionPattern]:
        """Simple text search on question_text"""
        rows = self.conn.execute(
            """
            SELECT * FROM patterns
            WHERE question_text LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (f"%{query}%", limit),
        ).fetchall()
        return [self._row_to_pattern(row) for row in rows]

    def get_stats(self) -> dict:
        """Get database statistics"""
        stats = {}

        # Total count
        stats["total"] = self.conn.execute(
            "SELECT COUNT(*) FROM patterns"
        ).fetchone()[0]

        # By question type
        type_rows = self.conn.execute(
            "SELECT question_type, COUNT(*) as cnt FROM patterns GROUP BY question_type"
        ).fetchall()
        stats["by_type"] = {row["question_type"]: row["cnt"] for row in type_rows}

        # By project
        project_rows = self.conn.execute(
            "SELECT project, COUNT(*) as cnt FROM patterns GROUP BY project ORDER BY cnt DESC LIMIT 20"
        ).fetchall()
        stats["by_project"] = {row["project"]: row["cnt"] for row in project_rows}

        # Date range
        date_row = self.conn.execute(
            "SELECT MIN(timestamp) as min_ts, MAX(timestamp) as max_ts FROM patterns"
        ).fetchone()
        stats["date_range"] = (date_row["min_ts"], date_row["max_ts"])

        return stats

    def _row_to_pattern(self, row: sqlite3.Row) -> DecisionPattern:
        """Convert database row to DecisionPattern"""
        options = []
        if row["options_json"]:
            options_data = json.loads(row["options_json"])
            options = [QuestionOption(**opt) for opt in options_data]

        return DecisionPattern(
            id=row["id"],
            project=row["project"],
            session_id=row["session_id"],
            tool_use_id=row["tool_use_id"],
            question_text=row["question_text"],
            question_header=row["question_header"] or "",
            question_type=QuestionType(row["question_type"] or "unknown"),
            options=options,
            context_before=row["context_before"] or "",
            thinking=row["thinking"],
            user_answer=row["user_answer"],
            is_selected_option=bool(row["is_selected_option"]),
            timestamp=datetime.fromisoformat(row["timestamp"]),
            extracted_at=datetime.fromisoformat(row["extracted_at"]),
        )
