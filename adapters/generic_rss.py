"""Adapter for polling arbitrary RSS/Atom feeds."""

from __future__ import annotations

import email.utils
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List

from .base import SourceAdapter, register


@register("generic_rss")
class GenericRSSAdapter(SourceAdapter):
    """Fetch items from configured RSS/Atom feeds."""

    def fetch(self) -> List[Dict[str, Any]]:
        feeds = self.config.get("feeds") or []
        items: List[Dict[str, Any]] = []
        for feed in feeds:
            try:
                response = self.get(feed, headers={"User-Agent": self.user_agent})
            except Exception:  # pragma: no cover - logged by caller
                continue
            try:
                root = ET.fromstring(response.text)
            except ET.ParseError:
                continue
            channel = root.find("channel")
            entries = channel.findall("item") if channel is not None else root.findall("entry")
            for entry in entries:
                title = self._text(entry, "title")
                description = self._text(entry, "description") or self._text(entry, "summary")
                content = self._text(entry, "content") or description
                link = self._text(entry, "link")
                if not link:
                    link_elem = entry.find("link")
                    if link_elem is not None:
                        link = link_elem.attrib.get("href", "")
                published = self._text(entry, "pubDate") or self._text(entry, "updated")
                timestamp = self._parse_date(published)
                text = " ".join(filter(None, [description, content]))
                items.append(
                    self.normalize_item(
                        title=title,
                        text=text,
                        url=link or feed,
                        source_id=self.name,
                        timestamp=timestamp,
                    )
                )
        return items

    def _text(self, element: ET.Element, tag: str) -> str:
        child = element.find(tag)
        if child is None:
            return ""
        return (child.text or "").strip()

    def _parse_date(self, value: str | None) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            parsed = email.utils.parsedate_to_datetime(value)
            if parsed is not None:
                return parsed.astimezone(timezone.utc)
        except (ValueError, TypeError):  # pragma: no cover - fallback path
            pass
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
