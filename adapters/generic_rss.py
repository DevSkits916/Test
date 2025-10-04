"""Adapter that polls RSS/Atom feeds without external deps."""

from __future__ import annotations

import datetime as dt
import email.utils
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

from .base import SourceAdapter, register


@register("generic_rss")
class GenericRSSAdapter(SourceAdapter):
    """Fetch entries from configured feeds."""

    def fetch(self) -> List[Dict[str, Any]]:
        feeds = self.config.get("feeds", []) or []
        items: List[Dict[str, Any]] = []
        for feed_url in feeds:
            try:
                response = self.get(feed_url, headers={"User-Agent": self.user_agent})
            except Exception:
                continue
            try:
                root = ET.fromstring(response.content)
            except ET.ParseError:
                self.logger.warning("Failed to parse feed: %s", feed_url)
                continue
            if root.tag.endswith("feed"):
                entries = root.findall("{*}entry")
                for entry in entries:
                    title = self._text(entry.find("{*}title"))
                    text = self._text(entry.find("{*}content")) or self._text(entry.find("{*}summary"))
                    link_el = entry.find("{*}link")
                    url = link_el.get("href") if link_el is not None else None
                    timestamp = self._parse_datetime(
                        self._text(entry.find("{*}updated")) or self._text(entry.find("{*}published"))
                    )
                    items.append(
                        {
                            "title": title,
                            "text": text,
                            "url": url or feed_url,
                            "source_id": self._text(entry.find("{*}id")) or (title or url or ""),
                            "timestamp_iso": timestamp,
                        }
                    )
            else:
                channel = root.find("channel")
                if channel is None:
                    continue
                for item in channel.findall("item"):
                    title = self._text(item.find("title"))
                    text = self._text(item.find("description"))
                    url = self._text(item.find("link"))
                    timestamp = self._parse_datetime(self._text(item.find("pubDate")))
                    items.append(
                        {
                            "title": title,
                            "text": text,
                            "url": url or feed_url,
                            "source_id": self._text(item.find("guid")) or (title or url or ""),
                            "timestamp_iso": timestamp,
                        }
                    )
        return items

    def _text(self, element: ET.Element | None) -> str:
        return (element.text or "").strip() if element is not None and element.text else ""

    def _parse_datetime(self, value: str | None) -> str:
        if not value:
            return dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            parsed = email.utils.parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc).isoformat()
        except Exception:
            return dt.datetime.now(dt.timezone.utc).isoformat()
