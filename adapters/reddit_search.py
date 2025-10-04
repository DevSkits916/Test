"""Adapter for Reddit search API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from .base import SourceAdapter, register


@register("reddit_search")
class RedditSearchAdapter(SourceAdapter):
    """Fetch posts via Reddit's search.json endpoint."""

    def fetch(self) -> List[Dict[str, Any]]:
        endpoint = self.config.get("endpoint", "https://www.reddit.com/search.json")
        query = self.config.get("query")
        if not query:
            return []
        params = {
            "q": query,
            "sort": "new",
            "limit": int(self.config.get("limit", 50)),
        }
        response = self.get(endpoint, params=params, headers={"User-Agent": self.user_agent})
        payload = response.json()
        children = payload.get("data", {}).get("children", [])
        items: List[Dict[str, Any]] = []
        for child in children:
            data = child.get("data", {})
            title = data.get("title", "")
            text = data.get("selftext", "")
            url = data.get("url", endpoint)
            created = data.get("created_utc")
            timestamp = (
                datetime.fromtimestamp(created, tz=timezone.utc)
                if isinstance(created, (int, float))
                else datetime.now(timezone.utc)
            )
            items.append(
                self.normalize_item(
                    title=title,
                    text=text,
                    url=url,
                    source_id=self.name,
                    timestamp=timestamp,
                )
            )
        return items
