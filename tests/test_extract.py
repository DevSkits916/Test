import os
import sys
from pathlib import Path

os.environ.setdefault("DISABLE_POLLING", "1")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import CodeExtractor, ExtractionSettings, app  # noqa: E402


def make_extractor():
    settings = ExtractionSettings(denylist=["HTTPS", "UPDATE"], min_len=5, max_len=8)
    return CodeExtractor(settings)


def test_extractor_basic_matches():
    extractor = make_extractor()
    text = "I have invite 7ZDCNP and also share code Q1W2E3."
    assert set(extractor.extract(text)) == {"7ZDCNP", "Q1W2E3"}


def test_extractor_rejects_denylist_and_short_codes():
    extractor = make_extractor()
    text = "Use https link and code ABCD or UPDATE soon"
    assert extractor.extract(text) == []


def test_extractor_requires_digits():
    extractor = make_extractor()
    text = "Potential codes SORAXX and INVITE"
    assert extractor.extract(text) == []


def test_build_snippet():
    extractor = make_extractor()
    text = "Here is the invite code 7ZDCNP you asked for in the middle of a sentence."
    snippet = extractor.build_snippet(text, "7ZDCNP", context=10)
    assert "7ZDCNP" in snippet
    assert len(snippet) <= len(text)


def test_health_endpoint():
    client = app.test_client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json == {"ok": True}
