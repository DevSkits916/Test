"""Adapter for subreddit JSON feeds."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from .base import SourceAdapter, register


@register("reddit_subs")
class RedditSubsAdapter(SourceAdapter):
    """Fetch new posts for configured subreddits."""

    def fetch(self) -> List[Dict[str, Any]]:
        subs = self.config.get("subs") or []
        limit = int(self.config.get("limit", 25))
        items: List[Dict[str, Any]] = []
        for sub in subs:
            url = f"https://www.reddit.com/r/{sub}/new.json"
            try:
                response = self.get(url, params={"limit": limit}, headers={"User-Agent": self.user_agent})
            except Exception:  # pragma: no cover - network errors are logged upstream
                continue
            payload = response.json()
            children = payload.get("data", {}).get("children", [])
            for child in children:
                data = child.get("data", {})
                title = data.get("title", "")
                text = data.get("selftext", "")
                permalink = data.get("permalink")
                post_url = f"https://www.reddit.com{permalink}" if permalink else data.get("url", url)
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
                        url=post_url,
                        source_id=f"{self.name}:{sub}",
                        timestamp=timestamp,
                    )
                )
        return items
