"""Best-effort adapter for scraping X/Twitter search pages."""

from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List

from .base import SourceAdapter, register


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: List[str] = []
        self._title_chunks: List[str] = []
        self._skip_stack: List[str] = []
        self._capture_title = False

    def handle_starttag(self, tag: str, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip_stack.append(tag)
        if tag == "title":
            self._capture_title = True

    def handle_endtag(self, tag: str):
        if self._skip_stack and self._skip_stack[-1] == tag:
            self._skip_stack.pop()
        if tag == "title":
            self._capture_title = False

    def handle_data(self, data: str):
        if self._skip_stack:
            return
        text = data.strip()
        if not text:
            return
        if self._capture_title:
            self._title_chunks.append(text)
        else:
            self._chunks.append(text)

    def get_text(self) -> str:
        return " ".join(self._chunks)

    def get_title(self) -> str:
        return " ".join(self._title_chunks)


@register("twitter_search")
class TwitterSearchAdapter(SourceAdapter):
    """Fetch HTML search results for configured queries."""

    def fetch(self) -> List[Dict[str, Any]]:
        urls = self.config.get("live_urls") or []
        items: List[Dict[str, Any]] = []
        for url in urls:
            try:
                response = self.get(
                    url,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                )
            except Exception:  # pragma: no cover - network failures logged upstream
                continue
            parser = _VisibleTextParser()
            parser.feed(response.text)
            title = parser.get_title() or "Twitter search"
            text = parser.get_text()
            items.append(
                self.normalize_item(
                    title=title,
                    text=text,
                    url=url,
                    source_id=self.name,
                    timestamp=datetime.now(timezone.utc),
                )
            )
        return items
