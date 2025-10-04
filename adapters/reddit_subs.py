"""Adapter that polls specific subreddit listings."""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List

from .base import SourceAdapter, register

SUB_URL_TEMPLATE = "https://www.reddit.com/r/{sub}/new.json"


@register("reddit_subs")
class RedditSubsAdapter(SourceAdapter):
    """Fetch new posts from configured subreddits."""

    def fetch(self) -> List[Dict[str, Any]]:
        subs = self.config.get("subs", []) or []
        limit = int(self.config.get("limit", 25))
        items: List[Dict[str, Any]] = []
        for sub in subs:
            url = SUB_URL_TEMPLATE.format(sub=sub)
            params = {"limit": limit}
            try:
                response = self.get(url, params=params, headers={"User-Agent": self.user_agent})
            except Exception:
                continue
            payload = response.json()
            for child in payload.get("data", {}).get("children", []):
                data = child.get("data", {})
                created = dt.datetime.utcfromtimestamp(data.get("created_utc", 0))
                items.append(
                    {
                        "title": data.get("title", ""),
                        "text": data.get("selftext", ""),
                        "url": f"https://www.reddit.com{data.get('permalink', '')}",
                        "source_id": f"{sub}:{data.get('id', '')}",
                        "timestamp_iso": created.replace(tzinfo=dt.timezone.utc).isoformat(),
                    }
                )
        return items
