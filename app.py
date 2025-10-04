"""Sora Invite Code Hunter application."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests
from flask import Flask, Response, jsonify, render_template, request

from adapters.base import SourceAdapter, create_adapters
import adapters.generic_html  # noqa: F401
import adapters.generic_rss  # noqa: F401
import adapters.reddit_search  # noqa: F401
import adapters.reddit_subs  # noqa: F401
from storage.memory_repo import InMemoryRepository
from storage.repo import CandidateRecord, CandidateRepository
from storage.sqlite_repo import SQLiteRepository

APP_NAME = "Sora Invite Code Hunter"
DEFAULT_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
DEFAULT_USER_AGENT = os.getenv("USER_AGENT", "sora-hunter/0.1")
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "config/sources.json"))

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s in %(name)s: %(message)s")
logger = logging.getLogger("sora_hunter")


@dataclass
class ExtractionSettings:
    min_len: int = 5
    max_len: int = 8
    denylist: Iterable[str] = ()


class CodeExtractor:
    """Extract invite code candidates from text."""

    def __init__(self, settings: ExtractionSettings):
        self.settings = settings
        pattern = rf"\b[A-Z0-9]{{{settings.min_len},{settings.max_len}}}\b"
        self.regex = re_compile(pattern)
        self.denylist = {token.upper() for token in settings.denylist}

    def extract(self, text: str | None) -> List[str]:
        if not text:
            return []
        matches: List[str] = []
        for match in self.regex.finditer(text.upper()):
            code = match.group(0)
            if not any(ch.isdigit() for ch in code):
                continue
            if code in self.denylist:
                continue
            if len(code) < self.settings.min_len or len(code) > self.settings.max_len:
                continue
            matches.append(code)
        return matches

    def build_snippet(self, text: str, code: str, context: int = 80) -> str:
        if not text:
            return code
        upper = text.upper()
        index = upper.find(code)
        if index == -1:
            index = max(0, len(text) // 2)
        start = max(0, index - context)
        end = min(len(text), index + len(code) + context)
        snippet = text[start:end].strip()
        snippet = re_sub(r"\s+", " ", snippet)
        return snippet


def re_compile(pattern: str):
    import re

    return re.compile(pattern, re.IGNORECASE)


def re_sub(pattern: str, repl: str, text: str) -> str:
    import re

    return re.sub(pattern, repl, text)


def load_config(path: Path) -> Dict[str, object]:
    if not path.exists():
        logger.warning("Config file %s not found, using defaults", path)
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class EventBroadcaster:
    """Simple fan-out broadcaster for SSE clients."""

    def __init__(self) -> None:
        self._clients: List[queue.Queue] = []
        self._lock = threading.Lock()

    def register(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._clients.append(q)
        return q

    def unregister(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def publish(self, data: Dict[str, object]) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(data)
            except queue.Full:  # pragma: no cover
                pass


class DiscordNotifier:
    def __init__(self, webhook_url: str | None) -> None:
        self.webhook_url = webhook_url
        self.session = requests.Session()

    def notify(self, candidate: CandidateRecord) -> None:
        if not self.webhook_url:
            return
        embed = {
            "title": f"New code: {candidate['code']}",
            "fields": [
                {"name": "Source", "value": str(candidate.get("source"))},
                {"name": "Discovered", "value": str(candidate.get("discovered_at"))},
                {"name": "Link", "value": str(candidate.get("url"))},
            ],
        }
        payload = {"embeds": [embed], "username": APP_NAME}
        try:
            response = self.session.post(self.webhook_url, json=payload, timeout=5)
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - notification failures shouldn't crash
            logger.warning("Failed to send Discord notification: %s", exc)


def create_repository() -> CandidateRepository:
    store = os.getenv("STORE", "memory").lower()
    if store == "sqlite":
        path = os.getenv("SQLITE_PATH", "data/codes.db")
        return SQLiteRepository(path)
    return InMemoryRepository()


config = load_config(CONFIG_PATH)
settings = ExtractionSettings(
    min_len=int(os.getenv("MIN_LEN", "5")),
    max_len=int(os.getenv("MAX_LEN", "8")),
    denylist=config.get("denylist_tokens", []),
)
extractor = CodeExtractor(settings)
repository = create_repository()
broadcaster = EventBroadcaster()
notifier = DiscordNotifier(os.getenv("DISCORD_WEBHOOK_URL"))
last_poll_iso: Optional[str] = None

app = Flask(__name__)


def parse_adapters() -> List[str]:
    adapters_env = os.getenv("ADAPTERS")
    if adapters_env:
        return [name.strip() for name in adapters_env.split(",") if name.strip()]
    return ["reddit_search", "reddit_subs", "generic_rss", "generic_html"]


def process_items(adapter: SourceAdapter, items: List[Dict[str, object]]) -> None:
    global last_poll_iso
    for item in items:
        text = " ".join(
            filter(
                None,
                [str(item.get("title", "")), str(item.get("text", ""))],
            )
        )
        codes = extractor.extract(text)
        for code in codes:
            candidate = build_candidate_record(code, adapter.name, item)
            inserted = repository.add_candidate(candidate)
            if inserted:
                notifier.notify(candidate)
                broadcaster.publish(candidate)
    last_poll_iso = dt.datetime.now(dt.timezone.utc).isoformat()


def build_candidate_record(code: str, source: str, item: Dict[str, object]) -> CandidateRecord:
    text = str(item.get("text", ""))
    snippet = extractor.build_snippet(text, code)
    discovered = dt.datetime.now(dt.timezone.utc).isoformat()
    return {
        "code": code.upper(),
        "source": source,
        "source_title": str(item.get("title", "")),
        "url": str(item.get("url", "")),
        "example_text": snippet,
        "discovered_at": discovered,
        "tried": 0,
        "hidden": 0,
    }


def poller(stop_event: threading.Event) -> None:
    adapters = create_adapters(parse_adapters(), config, user_agent=DEFAULT_USER_AGENT, logger=logger)
    logger.info("Polling adapters: %s", ", ".join(adapter.name for adapter in adapters))
    interval = max(10, DEFAULT_INTERVAL)
    while not stop_event.is_set():
        for adapter in adapters:
            try:
                items = adapter.fetch()
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status == 429:
                    logger.warning("Rate limited by %s, backing off", adapter.name)
                    time.sleep(interval)
                else:
                    logger.warning("Adapter %s failed: %s", adapter.name, exc)
                continue
            process_items(adapter, items)
        stop_event.wait(interval)


stop_event = threading.Event()
if os.getenv("DISABLE_POLLING") != "1":
    polling_thread = threading.Thread(target=poller, args=(stop_event,), daemon=True)
    polling_thread.start()
else:
    polling_thread = None


@app.route("/")
def index() -> str:
    return render_template("index.html", active_sources=parse_adapters())


@app.get("/api/snapshot")
def api_snapshot():
    latest = repository.get_latest(limit=25)
    totals = {
        "visible": repository.count(include_hidden=False),
        "all": repository.count(include_hidden=True),
    }
    return jsonify({"last_poll": last_poll_iso, "totals": totals, "candidates": latest})


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@app.get("/api/codes")
def api_codes():
    q = request.args.get("q")
    source = request.args.get("source")
    include_hidden = parse_bool(request.args.get("include_hidden"), False)
    include_tried = parse_bool(request.args.get("include_tried"), True)
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(500, max(1, int(request.args.get("page_size", 100))))
    offset = (page - 1) * page_size
    items = repository.list(
        q=q,
        source=source,
        include_hidden=include_hidden,
        include_tried=include_tried,
        offset=offset,
        limit=page_size,
    )
    total_visible = repository.count(q=q, source=source, include_hidden=include_hidden, include_tried=include_tried)
    return jsonify({"items": items, "total_visible": total_visible})


@app.post("/api/codes/<code>/tried")
def api_mark_tried(code: str):
    repository.mark_tried(code, True)
    return jsonify({"ok": True})


@app.post("/api/codes/<code>/hide")
def api_toggle_hidden(code: str):
    hidden = repository.toggle_hidden(code)
    if hidden is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "hidden": hidden})


@app.delete("/api/codes/<code>")
def api_delete(code: str):
    deleted = repository.delete(code)
    if not deleted:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True})


@app.get("/events")
def events():
    q = broadcaster.register()

    def stream():
        try:
            while True:
                try:
                    data = q.get(timeout=30)
                except queue.Empty:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                yield f"data: {json.dumps(data)}\n\n"
        finally:
            broadcaster.unregister(q)

    headers = {"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "Connection": "keep-alive"}
    return Response(stream(), headers=headers)


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


def shutdown():  # pragma: no cover - used on interpreter exit
    stop_event.set()
    if polling_thread:
        polling_thread.join(timeout=5)


import atexit
import re

atexit.register(shutdown)

if __name__ == "__main__":
    app.run(host=os.getenv("BIND", "0.0.0.0"), port=int(os.getenv("PORT", "3000")))
