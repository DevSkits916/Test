"""Adapter that performs lightweight HTML scraping."""

from __future__ import annotations

import datetime as dt
import re
from html.parser import HTMLParser
from typing import Any, Dict, List

from .base import SourceAdapter, register

SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\\1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: List[str] = []

    def handle_data(self, data: str) -> None:  # pragma: no cover - trivial
        text = data.strip()
        if text:
            self.chunks.append(text)

    def get_text(self) -> str:
        return " ".join(self.chunks)


@register("generic_html")
class GenericHTMLAdapter(SourceAdapter):
    """Fetch configured pages and extract visible text."""

    def fetch(self) -> List[Dict[str, Any]]:
        urls = self.config.get("urls", []) or []
        items: List[Dict[str, Any]] = []
        for url in urls:
            try:
                response = self.get(url, headers={"User-Agent": self.user_agent})
            except Exception:
                continue
            html = response.text
            title_match = TITLE_RE.search(html)
            title = self._clean_text(title_match.group(1) if title_match else url)
            body = SCRIPT_STYLE_RE.sub(" ", html)
            extractor = _TextExtractor()
            try:
                extractor.feed(body)
            except Exception:
                # fallback to regex stripping
                text = TAG_RE.sub(" ", body)
            else:
                text = extractor.get_text()
            normalized = {
                "title": title,
                "text": self._clean_text(text),
                "url": url,
                "source_id": url,
                "timestamp_iso": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            items.append(normalized)
        return items

    def _clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()
