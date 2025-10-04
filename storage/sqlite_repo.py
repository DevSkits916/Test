"""SQLite-backed repository."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, List

from .repo import CandidateRecord, CandidateRepository

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    source TEXT,
    source_title TEXT,
    url TEXT,
    example_text TEXT,
    discovered_at TEXT,
    tried INTEGER DEFAULT 0,
    hidden INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_candidates_code ON candidates(code);
CREATE INDEX IF NOT EXISTS idx_candidates_discovered ON candidates(discovered_at DESC);
"""


class SQLiteRepository(CandidateRepository):
    def __init__(self, path: str) -> None:
        db_path = Path(path)
        if not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA)

    def add_candidate(self, candidate: CandidateRecord) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO candidates(code, source, source_title, url, example_text, discovered_at, tried, hidden)
                VALUES (:code, :source, :source_title, :url, :example_text, :discovered_at, :tried, :hidden)
                """,
                candidate,
            )
        return cursor.rowcount > 0

    def bulk_add(self, candidates: Iterable[CandidateRecord]) -> int:
        with self.conn:
            cursor = self.conn.executemany(
                """
                INSERT OR IGNORE INTO candidates(code, source, source_title, url, example_text, discovered_at, tried, hidden)
                VALUES (:code, :source, :source_title, :url, :example_text, :discovered_at, :tried, :hidden)
                """,
                list(candidates),
            )
        return cursor.rowcount or 0

    def mark_tried(self, code: str, tried: bool = True) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE candidates SET tried = ? WHERE code = ?",
                (1 if tried else 0, code.upper()),
            )
        return cursor.rowcount > 0

    def toggle_hidden(self, code: str):
        with self.conn:
            cursor = self.conn.execute(
                "SELECT hidden FROM candidates WHERE code = ?",
                (code.upper(),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            new_value = 0 if row["hidden"] else 1
            self.conn.execute("UPDATE candidates SET hidden = ? WHERE code = ?", (new_value, code.upper()))
        return bool(new_value)

    def delete(self, code: str) -> bool:
        with self.conn:
            cursor = self.conn.execute("DELETE FROM candidates WHERE code = ?", (code.upper(),))
        return cursor.rowcount > 0

    def list(self, *, q: str | None = None, source: str | None = None, include_hidden: bool = False,
             include_tried: bool = True, offset: int = 0, limit: int = 100) -> List[CandidateRecord]:
        clauses = ["1=1"]
        params: list = []
        if not include_hidden:
            clauses.append("hidden = 0")
        if not include_tried:
            clauses.append("tried = 0")
        if source:
            clauses.append("source = ?")
            params.append(source)
        if q:
            like = f"%{q.upper()}%"
            clauses.append("(UPPER(code) LIKE ? OR UPPER(source_title) LIKE ? OR UPPER(example_text) LIKE ?)")
            params.extend([like, like, like])
        sql = "SELECT code, source, source_title, url, example_text, discovered_at, tried, hidden FROM candidates WHERE " + " AND ".join(clauses) + " ORDER BY datetime(discovered_at) DESC, rowid DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = self.conn.execute(sql, params)
        rows = cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    def count(self, *, q: str | None = None, source: str | None = None, include_hidden: bool = False,
              include_tried: bool = True) -> int:
        clauses = ["1=1"]
        params: list = []
        if not include_hidden:
            clauses.append("hidden = 0")
        if not include_tried:
            clauses.append("tried = 0")
        if source:
            clauses.append("source = ?")
            params.append(source)
        if q:
            like = f"%{q.upper()}%"
            clauses.append("(UPPER(code) LIKE ? OR UPPER(source_title) LIKE ? OR UPPER(example_text) LIKE ?)")
            params.extend([like, like, like])
        sql = "SELECT COUNT(*) FROM candidates WHERE " + " AND ".join(clauses)
        cursor = self.conn.execute(sql, params)
        return cursor.fetchone()[0]

    def exists(self, code: str) -> bool:
        cursor = self.conn.execute("SELECT 1 FROM candidates WHERE code = ?", (code.upper(),))
        return cursor.fetchone() is not None

    def get_latest(self, limit: int = 20) -> List[CandidateRecord]:
        cursor = self.conn.execute(
            "SELECT code, source, source_title, url, example_text, discovered_at, tried, hidden FROM candidates ORDER BY datetime(discovered_at) DESC, rowid DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def _row_to_dict(self, row: sqlite3.Row) -> CandidateRecord:
        return {
            "code": row["code"],
            "source": row["source"],
            "source_title": row["source_title"],
            "url": row["url"],
            "example_text": row["example_text"],
            "discovered_at": row["discovered_at"],
            "tried": row["tried"],
            "hidden": row["hidden"],
        }
