"""Base classes and registry for polling adapters."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

REGISTRY: Dict[str, type["SourceAdapter"]] = {}


def register(name: str):
    """Decorator that registers the adapter under the provided name."""

    def _decorator(cls: type["SourceAdapter"]) -> type["SourceAdapter"]:
        REGISTRY[name] = cls
        cls.name = name
        return cls

    return _decorator


class SourceAdapter(ABC):
    """Abstract interface for fetching potential invite code content."""

    name: str = "base"

    def __init__(
        self,
        config: Dict[str, Any],
        *,
        session: Optional[requests.Session] = None,
        user_agent: str,
        logger: logging.Logger,
    ) -> None:
        self.config = config or {}
        self.user_agent = user_agent
        self.logger = logger
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            }
        )
        self.timeout = int(self.config.get("timeout", 15))

    @abstractmethod
    def fetch(self) -> List[Dict[str, Any]]:
        """Return a list of normalized items."""

    # -- HTTP helpers -----------------------------------------------------
    def get(self, url: str, **kwargs: Any) -> requests.Response:
        timeout = kwargs.pop("timeout", self.timeout)
        try:
            response = self.session.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:  # pragma: no cover - logging path
            self.logger.warning("%s adapter request failed: %s", self.name, exc)
            raise

    def head(self, url: str, **kwargs: Any) -> requests.Response:
        timeout = kwargs.pop("timeout", self.timeout)
        try:
            response = self.session.head(url, timeout=timeout, allow_redirects=True, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:  # pragma: no cover - logging path
            self.logger.warning("%s adapter HEAD request failed: %s", self.name, exc)
            raise

    # -- Normalisation helpers -------------------------------------------
    def normalize_item(
        self,
        *,
        title: str,
        text: str,
        url: str,
        source_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        return {
            "title": title or "",
            "text": text or "",
            "url": url or "",
            "source_id": source_id or self.name,
            "timestamp_iso": (timestamp or datetime.now(timezone.utc)).isoformat(),
        }


def create_adapters(
    names: List[str],
    config: Dict[str, Any],
    *,
    session: Optional[requests.Session],
    user_agent: str,
    logger: logging.Logger,
) -> List[SourceAdapter]:
    """Instantiate adapters listed in ``names`` with config scoped to each."""

    instances: List[SourceAdapter] = []
    for name in names:
        cls = REGISTRY.get(name)
        if not cls:
            logger.warning("Adapter %s not found in registry", name)
            continue
        adapter_config = config.get(name, {}) if config else {}
        if adapter_config is not None and not adapter_config.get("enabled", True):
            continue
        instances.append(
            cls(adapter_config or {}, session=session, user_agent=user_agent, logger=logger)
        )
    return instances
