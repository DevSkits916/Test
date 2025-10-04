"""Base classes and registry for polling adapters."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

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

    def __init__(self, config: Dict[str, Any], *, user_agent: str, logger: logging.Logger):
        self.config = config or {}
        self.user_agent = user_agent
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            }
        )

    @abstractmethod
    def fetch(self) -> List[Dict[str, Any]]:
        """Return a list of normalized items."""

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """Wrapper around ``requests.get`` with sane defaults and logging."""

        timeout = kwargs.pop("timeout", 10)
        try:
            response = self.session.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:  # pragma: no cover - logging path
            self.logger.warning("%s adapter request failed: %s", self.name, exc)
            raise

    def get_with_reddit_fallback(self, url: str, **kwargs: Any) -> requests.Response:
        """Attempt request and retry via api.reddit.com on 403 responses."""

        try:
            return self.get(url, **kwargs)
        except requests.HTTPError as exc:
            response = getattr(exc, "response", None)
            if response is not None and response.status_code == 403 and "www.reddit.com" in url:
                alt_url = url.replace("www.reddit.com", "api.reddit.com")
                self.logger.info("%s adapter retrying via api.reddit.com after 403", self.name)
                return self.get(alt_url, **kwargs)
            raise


def create_adapters(names: List[str], config: Dict[str, Any], *, user_agent: str, logger: logging.Logger) -> List[SourceAdapter]:
    """Instantiate adapters listed in ``names`` with config scoped to each."""

    instances: List[SourceAdapter] = []
    for name in names:
        cls = REGISTRY.get(name)
        if not cls:
            logger.warning("Adapter %s not found in registry", name)
            continue
        adapter_config = config.get(name, {}) if config else {}
        instances.append(cls(adapter_config, user_agent=user_agent, logger=logger))
    return instances
