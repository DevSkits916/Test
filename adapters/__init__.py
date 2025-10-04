"""Adapter package exports."""

from . import generic_html, generic_rss, reddit_search, reddit_subs, twitter_search  # noqa: F401
from .base import create_adapters, register, SourceAdapter

__all__ = [
    "create_adapters",
    "register",
    "SourceAdapter",
]
