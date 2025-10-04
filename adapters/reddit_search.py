"""Adapter that queries Reddit search JSON endpoint."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List

from .base import SourceAdapter, register

REDDIT_SEARCH_URL = "https://www.reddit.com/search.json"


@register("reddit_search")
class RedditSearchAdapter(SourceAdapter):
    """Search Reddit for matching posts."""

    def fetch(self) -> List[Dict[str, Any]]:
        query = self.config.get("query", "Sora invite code")
        limit = int(self.config.get("limit", 50))
        params = {"q": query, "sort": "new", "limit": limit, "restrict_sr": False}
        try:
            response = self.get(REDDIT_SEARCH_URL, params=params, headers={"User-Agent": self.user_agent})
        except Exception:
            return []
        payload = response.json()
        items: List[Dict[str, Any]] = []
        for child in payload.get("data", {}).get("children", []):
            data = child.get("data", {})
            created = dt.datetime.utcfromtimestamp(data.get("created_utc", 0))
            items.append(
                {
                    "title": data.get("title", ""),
                    "text": data.get("selftext", ""),
                    "url": f"https://www.reddit.com{data.get('permalink', '')}",
                    "source_id": data.get("id", ""),
                    "timestamp_iso": created.replace(tzinfo=dt.timezone.utc).isoformat(),
                }
            )
        return items
