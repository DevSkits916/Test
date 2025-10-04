"""In-memory candidate repository."""

from __future__ import annotations

import threading
from typing import Dict, Iterable, List

from .repo import CandidateRecord, CandidateRepository


class InMemoryRepository(CandidateRepository):
    def __init__(self) -> None:
        self._store: Dict[str, CandidateRecord] = {}
        self._lock = threading.Lock()

    def add_candidate(self, candidate: CandidateRecord) -> bool:
        code = str(candidate["code"]).upper()
        with self._lock:
            if code in self._store:
                return False
            self._store[code] = dict(candidate)
        return True

    def bulk_add(self, candidates: Iterable[CandidateRecord]) -> int:
        inserted = 0
        for candidate in candidates:
            if self.add_candidate(candidate):
                inserted += 1
        return inserted

    def mark_tried(self, code: str, tried: bool = True) -> bool:
        key = code.upper()
        with self._lock:
            item = self._store.get(key)
            if not item:
                return False
            item["tried"] = 1 if tried else 0
            return True

    def toggle_hidden(self, code: str):
        key = code.upper()
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            hidden = int(item.get("hidden", 0))
            hidden = 0 if hidden else 1
            item["hidden"] = hidden
            return bool(hidden)

    def delete(self, code: str) -> bool:
        key = code.upper()
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def list(self, *, q: str | None = None, source: str | None = None, include_hidden: bool = False,
             include_tried: bool = True, offset: int = 0, limit: int = 100) -> List[CandidateRecord]:
        with self._lock:
            records = list(self._store.values())
        q_upper = q.upper() if q else None
        filtered: List[CandidateRecord] = []
        for record in records:
            if not include_hidden and int(record.get("hidden", 0)):
                continue
            if not include_tried and int(record.get("tried", 0)):
                continue
            if source and record.get("source") != source:
                continue
            if q_upper:
                haystack = f"{record.get('code', '')} {record.get('source_title', '')} {record.get('example_text', '')}".upper()
                if q_upper not in haystack:
                    continue
            filtered.append(record)
        filtered.sort(key=lambda r: str(r.get("discovered_at", "")), reverse=True)
        return filtered[offset: offset + limit]

    def count(self, *, q: str | None = None, source: str | None = None, include_hidden: bool = False,
              include_tried: bool = True) -> int:
        return len(self.list(q=q, source=source, include_hidden=include_hidden,
                             include_tried=include_tried, offset=0, limit=10_000_000))

    def exists(self, code: str) -> bool:
        return code.upper() in self._store

    def get_latest(self, limit: int = 20) -> List[CandidateRecord]:
        return self.list(offset=0, limit=limit)
