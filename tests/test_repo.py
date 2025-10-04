import os
import sys
from pathlib import Path

os.environ.setdefault("DISABLE_POLLING", "1")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from storage.memory_repo import InMemoryRepository
from storage.sqlite_repo import SQLiteRepository


def sample_candidate(code: str, **overrides):
    base = {
        "code": code,
        "source": "test",
        "source_title": "Example",
        "url": "https://example.com",
        "example_text": "Example snippet",
        "discovered_at": "2024-01-01T00:00:00+00:00",
        "tried": 0,
        "hidden": 0,
    }
    base.update(overrides)
    return base


def check_repository(repo):
    assert repo.add_candidate(sample_candidate("ABC12"))
    assert not repo.add_candidate(sample_candidate("ABC12"))
    assert repo.exists("ABC12")

    repo.mark_tried("ABC12", True)
    entries = repo.list()
    assert entries[0]["tried"] == 1

    hidden = repo.toggle_hidden("ABC12")
    assert hidden is True
    hidden = repo.toggle_hidden("ABC12")
    assert hidden is False

    latest = repo.get_latest()
    assert latest

    assert repo.count_since("2023-12-31T00:00:00+00:00") >= 1

    assert repo.delete("ABC12")
    assert not repo.delete("ABC12")
    assert repo.count() == 0


def test_memory_repository():
    repo = InMemoryRepository()
    check_repository(repo)


def test_sqlite_repository(tmp_path):
    db_path = tmp_path / "test.db"
    repo = SQLiteRepository(str(db_path))
    check_repository(repo)
    assert repo.count() == 0
