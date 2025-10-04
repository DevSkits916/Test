"""Repository abstraction for storing candidate invite codes."""

from __future__ import annotations

import abc
from typing import Dict, Iterable, List, Optional

CandidateRecord = Dict[str, object]


class CandidateRepository(abc.ABC):
    """Interface for candidate persistence."""

    @abc.abstractmethod
    def add_candidate(self, candidate: CandidateRecord) -> bool:
        """Add a candidate if not already present.

        Returns ``True`` if inserted, ``False`` if it already existed.
        """

    @abc.abstractmethod
    def bulk_add(self, candidates: Iterable[CandidateRecord]) -> int:
        """Add many candidates, returning number of inserted rows."""

    @abc.abstractmethod
    def mark_tried(self, code: str, tried: bool = True) -> bool:
        """Mark a candidate as tried."""

    @abc.abstractmethod
    def toggle_hidden(self, code: str) -> Optional[bool]:
        """Toggle hidden status, returning new hidden value or ``None``."""

    @abc.abstractmethod
    def delete(self, code: str) -> bool:
        """Delete candidate by code."""

    @abc.abstractmethod
    def list(self, *, q: str | None = None, source: str | None = None, include_hidden: bool = False,
             include_tried: bool = True, offset: int = 0, limit: int = 100) -> List[CandidateRecord]:
        """List candidates ordered by newest first."""

    @abc.abstractmethod
    def count(self, *, q: str | None = None, source: str | None = None, include_hidden: bool = False,
              include_tried: bool = True) -> int:
        """Return number of candidates for filters."""

    @abc.abstractmethod
    def exists(self, code: str) -> bool:
        """Check if code exists."""

    @abc.abstractmethod
    def get_latest(self, limit: int = 20) -> List[CandidateRecord]:
        """Get latest candidates for SSE bootstrap."""
