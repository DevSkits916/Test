"""Sora Invite Code Hunter application."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_file,
)
from logging.handlers import RotatingFileHandler

from adapters import create_adapters
from adapters.base import SourceAdapter
from storage.memory_repo import InMemoryRepository
from storage.repo import CandidateRecord, CandidateRepository
from storage.sqlite_repo import SQLiteRepository

APP_NAME = "Sora Invite Code Hunter"
CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "config"))
SOURCES_PATH = CONFIG_DIR / "sources.json"
DENYLIST_PATH = CONFIG_DIR / "denylist.json"
LOG_DIR = Path("logs")
LOG_FILES = {
    "app": LOG_DIR / "app.log",
    "poller": LOG_DIR / "poller.log",
    "source_health": LOG_DIR / "source_health.log",
}
DEFAULT_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
DEFAULT_USER_AGENT = os.getenv("USER_AGENT", "sora-hunter/0.1")
DEFAULT_BIND = os.getenv("BIND", "0.0.0.0")
DEFAULT_PORT = int(os.getenv("PORT", "3000"))
MAX_BACKOFF = 300

# Ensure log directory exists early
LOG_DIR.mkdir(parents=True, exist_ok=True)


def re_compile(pattern: str):
    import re

    return re.compile(pattern, re.IGNORECASE)


def re_sub(pattern: str, repl: str, text: str) -> str:
    import re

    return re.sub(pattern, repl, text)


class StructuredFormatter(logging.Formatter):
    """Formatter that emits ISO timestamp, level, component, message, extras JSON."""

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatting only
        timestamp = datetime.now(timezone.utc).isoformat()
        component = getattr(record, "component", record.name)
        extras = getattr(record, "extras", {})
        extras_json = json.dumps(extras, sort_keys=True) if extras else "{}"
        message = super().format(record)
        return f"{timestamp} | {record.levelname} | {component} | {message} | {extras_json}"


def configure_logger(name: str, filename: Path) -> logging.Logger:
    formatter = StructuredFormatter("%(message)s")
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    file_handler = RotatingFileHandler(filename, maxBytes=512_000, backupCount=5)
    file_handler.setFormatter(formatter)
    logger.handlers = [stream_handler, file_handler]
    return logger


APP_LOGGER = configure_logger("app", LOG_FILES["app"])
POLLER_LOGGER = configure_logger("poller", LOG_FILES["poller"])
HEALTH_LOGGER = configure_logger("source_health", LOG_FILES["source_health"])


@dataclass
class ExtractionSettings:
    min_len: int = 5
    max_len: int = 8
    denylist: Iterable[str] = ()


class CodeExtractor:
    """Extract invite code candidates from text based on heuristics."""

    URL_PATTERN = re_compile(r"https?://[^\s]+")

    def __init__(self, settings: ExtractionSettings):
        self.settings = settings
        self.pattern = re_compile(rf"\b[A-Z0-9]{{{settings.min_len},{settings.max_len}}}\b")
        self.denylist = {token.upper() for token in settings.denylist}

    def extract(self, text: str | None) -> List[str]:
        if not text:
            return []
        cleaned = self.URL_PATTERN.sub(" ", text)
        cleaned_upper = cleaned.upper()
        matches: List[str] = []
        for match in self.pattern.finditer(cleaned_upper):
            token = match.group(0).strip().upper()
            if token in self.denylist:
                continue
            if not any(ch.isdigit() for ch in token):
                continue
            if token.isalpha():
                continue
            if len(set(token)) == 1:
                continue
            if token.isdigit() and self._is_strictly_ascending(token):
                continue
            if not (self.settings.min_len <= len(token) <= self.settings.max_len):
                continue
            matches.append(token)
        return matches

    def build_snippet(self, text: str, code: str, context: int = 120) -> str:
        if not text:
            return code
        upper = text.upper()
        index = upper.find(code.upper())
        if index == -1:
            index = max(0, len(text) // 2)
        start = max(0, index - context)
        end = min(len(text), index + len(code) + context)
        snippet = text[start:end].strip()
        return re_sub(r"\s+", " ", snippet)

    def _is_strictly_ascending(self, token: str) -> bool:
        if len(token) <= 1:
            return False
        deltas = [int(token[i + 1]) - int(token[i]) for i in range(len(token) - 1)]
        return all(delta == 1 for delta in deltas)


class EventBroadcaster:
    """Fan-out broadcaster for SSE clients."""

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

    def publish(self, payload: Dict[str, object]) -> None:
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.put_nowait(payload)
            except queue.Full:  # pragma: no cover - safety net
                pass


class DiscordNotifier:
    def __init__(self, webhook_url: str | None) -> None:
        self.webhook_url = webhook_url
        self.session = requests.Session()

    def notify(self, candidate: CandidateRecord) -> None:
        if not self.webhook_url:
            return
        embed = {
            "title": f"New Sora code: {candidate['code']}",
            "fields": [
                {"name": "Source", "value": str(candidate.get("source"))},
                {"name": "Discovered", "value": str(candidate.get("discovered_at"))},
                {"name": "Link", "value": str(candidate.get("url")) or "(none)"},
            ],
        }
        payload = {"embeds": [embed], "username": APP_NAME}
        try:
            response = self.session.post(self.webhook_url, json=payload, timeout=5)
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - notification best-effort
            APP_LOGGER.warning(
                "Failed to send Discord webhook",
                extra={"component": "notifications", "extras": {"error": str(exc)}}
            )


class SourceHealthChecker:
    """Verifies configured URLs via HEAD/GET and caches results."""

    def __init__(self, session: requests.Session):
        self.session = session
        self._lock = threading.Lock()
        self._statuses: Dict[str, Dict[str, object]] = {}
        self._urls: List[str] = []

    def prime(self, urls: Iterable[str]) -> None:
        self._urls = sorted({url for url in urls if url})

    def check_all(self) -> List[Dict[str, object]]:
        results = []
        for url in self._urls:
            results.append(self._check(url))
        return results

    def recheck(self) -> List[Dict[str, object]]:
        return self.check_all()

    def get_statuses(self) -> List[Dict[str, object]]:
        with self._lock:
            return sorted(self._statuses.values(), key=lambda item: item["url"])

    def _check(self, url: str) -> Dict[str, object]:
        now_iso = datetime.now(timezone.utc).isoformat()
        status: Dict[str, object] = {
            "url": url,
            "ok": False,
            "status_code": None,
            "last_checked_iso": now_iso,
            "error": None,
        }
        try:
            response = self.session.head(url, timeout=5, allow_redirects=True)
            status["status_code"] = response.status_code
            if 200 <= response.status_code < 400:
                status["ok"] = True
            elif response.status_code in {405, 403}:
                raise requests.HTTPError("HEAD not allowed", response=response)
            else:
                status["error"] = f"HEAD status {response.status_code}"
        except requests.RequestException as exc:
            try:
                response = self.session.get(
                    url,
                    timeout=5,
                    headers={"Range": "bytes=0-0", "User-Agent": DEFAULT_USER_AGENT},
                    allow_redirects=True,
                )
                status["status_code"] = response.status_code
                status["ok"] = 200 <= response.status_code < 400
                if not status["ok"]:
                    status["error"] = f"GET status {response.status_code}"
            except requests.RequestException as get_exc:
                status["error"] = str(exc)
                status["status_code"] = None
                status["ok"] = False
                status["error"] = str(get_exc)
        with self._lock:
            self._statuses[url] = status
        HEALTH_LOGGER.info(
            "Source check",
            extra={
                "component": "health",
                "extras": {"url": url, "ok": status["ok"], "status_code": status["status_code"]},
            },
        )
        return status


def load_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"Missing configuration file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_sources_config() -> Dict[str, object]:
    config = load_json(SOURCES_PATH)
    if not isinstance(config, dict):
        raise ValueError("sources.json must contain an object")
    return config


def load_denylist() -> List[str]:
    data = load_json(DENYLIST_PATH)
    if not isinstance(data, list):
        raise ValueError("denylist.json must contain a list of strings")
    return [str(item).upper() for item in data]


def create_repository() -> CandidateRepository:
    store = os.getenv("STORE", "memory").lower()
    if store == "sqlite":
        path = os.getenv("SQLITE_PATH", "data/codes.db")
        return SQLiteRepository(path)
    return InMemoryRepository()


# -- Application state -----------------------------------------------------
sources_config = load_sources_config()
denylist_tokens = load_denylist()
settings = ExtractionSettings(
    min_len=int(os.getenv("MIN_LEN", "5")),
    max_len=int(os.getenv("MAX_LEN", "8")),
    denylist=denylist_tokens,
)
extractor = CodeExtractor(settings)
repository = create_repository()
broadcaster = EventBroadcaster()
notifier = DiscordNotifier(os.getenv("DISCORD_WEBHOOK_URL"))
last_poll_iso: Optional[str] = None
active_adapter_names: List[str] = []

polling_session = requests.Session()
polling_session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
health_checker = SourceHealthChecker(polling_session)

health_urls: List[str] = []
rs_config = sources_config.get("reddit_search", {}) or {}
endpoint = rs_config.get("endpoint")
if endpoint:
    health_urls.append(endpoint)
subs_config = sources_config.get("reddit_subs", {}) or {}
for sub in subs_config.get("subs", []) or []:
    health_urls.append(f"https://www.reddit.com/r/{sub}/new.json")
twitter_config = sources_config.get("twitter_search", {}) or {}
health_urls.extend(twitter_config.get("live_urls", []) or [])
health_urls.extend((sources_config.get("generic_rss", {}) or {}).get("feeds", []) or [])
health_urls.extend((sources_config.get("generic_html", {}) or {}).get("urls", []) or [])
health_checker.prime(health_urls)
health_checker.check_all()

APP_LOGGER.info(
    "Configuration loaded",
    extra={
        "component": "startup",
        "extras": {
            "min_len": settings.min_len,
            "max_len": settings.max_len,
            "store": os.getenv("STORE", "memory"),
        },
    },
)


# -- Polling ---------------------------------------------------------------
class AdapterState:
    def __init__(self, adapter: SourceAdapter, interval: int) -> None:
        self.adapter = adapter
        self.interval = interval
        self.backoff = 0
        self.next_run = time.time()

    def schedule_next(self) -> None:
        delay = self.backoff if self.backoff else self.interval
        self.next_run = time.time() + max(5, delay)

    def record_success(self) -> None:
        self.backoff = 0
        self.schedule_next()

    def record_failure(self, *, rate_limited: bool = False) -> None:
        base = self.interval
        if rate_limited:
            self.backoff = min(MAX_BACKOFF, max(self.backoff * 2 if self.backoff else base * 2, base))
        else:
            self.backoff = min(MAX_BACKOFF, max(self.backoff * 2 if self.backoff else base, base))
        self.schedule_next()


def parse_adapter_names() -> List[str]:
    adapters_env = os.getenv("ADAPTERS")
    if adapters_env:
        return [name.strip() for name in adapters_env.split(",") if name.strip()]
    return ["reddit_search", "reddit_subs", "twitter_search", "generic_rss", "generic_html"]


adapter_names = parse_adapter_names()
adapters: List[SourceAdapter] = create_adapters(
    adapter_names,
    sources_config,
    session=polling_session,
    user_agent=DEFAULT_USER_AGENT,
    logger=POLLER_LOGGER,
)
active_adapter_names = [adapter.name for adapter in adapters]


def build_candidate_record(code: str, source: str, item: Dict[str, object]) -> CandidateRecord:
    text = str(item.get("text", ""))
    snippet = extractor.build_snippet(text, code)
    discovered = datetime.now(timezone.utc).isoformat()
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


def process_items(adapter: SourceAdapter, items: List[Dict[str, object]]) -> int:
    inserted = 0
    for item in items:
        title = str(item.get("title", ""))
        text = str(item.get("text", ""))
        combined = f"{title}\n{text}".strip()
        codes = extractor.extract(combined)
        for code in codes:
            candidate = build_candidate_record(code, str(item.get("source_id", adapter.name)), item)
            if repository.add_candidate(candidate):
                inserted += 1
                broadcaster.publish(candidate)
                notifier.notify(candidate)
    return inserted


def poller(stop_event: threading.Event) -> None:
    global last_poll_iso
    states = [AdapterState(adapter, DEFAULT_INTERVAL) for adapter in adapters]
    if not states:
        APP_LOGGER.warning(
            "No adapters configured",
            extra={"component": "poller", "extras": {}},
        )
        return
    APP_LOGGER.info(
        "Starting poller",
        extra={"component": "poller", "extras": {"adapters": active_adapter_names, "interval": DEFAULT_INTERVAL}},
    )
    while not stop_event.is_set():
        now = time.time()
        for state in states:
            if now < state.next_run:
                continue
            adapter = state.adapter
            try:
                items = adapter.fetch()
                new_count = process_items(adapter, items)
                POLLER_LOGGER.info(
                    "Adapter run",
                    extra={
                        "component": adapter.name,
                        "extras": {"items": len(items), "new_codes": new_count},
                    },
                )
                state.record_success()
            except requests.HTTPError as exc:
                response = exc.response
                rate_limited = bool(response is not None and response.status_code == 429)
                POLLER_LOGGER.warning(
                    "Adapter error",
                    extra={
                        "component": adapter.name,
                        "extras": {"error": str(exc), "status_code": getattr(response, "status_code", None)},
                    },
                )
                state.record_failure(rate_limited=rate_limited)
            except Exception as exc:  # pragma: no cover - defensive logging
                POLLER_LOGGER.warning(
                    "Adapter exception",
                    extra={"component": adapter.name, "extras": {"error": str(exc)}},
                )
                state.record_failure()
        if states:
            last_poll_iso = datetime.now(timezone.utc).isoformat()
        stop_event.wait(1)


stop_event = threading.Event()
if os.getenv("DISABLE_POLLING") != "1":
    polling_thread = threading.Thread(target=poller, args=(stop_event,), daemon=True)
    polling_thread.start()
else:
    polling_thread = None


app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.route("/")
def index() -> str:
    return render_template("index.html", app_name=APP_NAME)


@app.get("/api/snapshot")
def api_snapshot():
    latest = repository.get_latest(limit=200)
    totals = {
        "visible": repository.count(include_hidden=False, include_tried=False),
        "all": repository.count(include_hidden=True, include_tried=True),
    }
    since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    totals["last_24h"] = repository.count_since(since_24h, include_hidden=False)
    return jsonify(
        {
            "last_poll": last_poll_iso,
            "totals": totals,
            "sources_health": health_checker.get_statuses(),
            "active_sources": active_adapter_names,
            "candidates": latest,
        }
    )


def parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@app.get("/api/codes")
def api_codes():
    q = request.args.get("q")
    source = request.args.get("source")
    include_hidden = parse_bool(request.args.get("include_hidden"), False)
    include_tried = parse_bool(request.args.get("include_tried"), False)
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
    total = repository.count(
        q=q,
        source=source,
        include_hidden=include_hidden,
        include_tried=include_tried,
    )
    return jsonify({"items": items, "total": total})


@app.post("/api/codes/<code>/tried")
def api_mark_tried(code: str):
    updated = repository.mark_tried(code, True)
    return jsonify({"ok": bool(updated)})


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


def _filtered_items_for_export() -> List[CandidateRecord]:
    q = request.args.get("q")
    source = request.args.get("source")
    include_hidden = parse_bool(request.args.get("include_hidden"), False)
    include_tried = parse_bool(request.args.get("include_tried"), False)
    limit = min(5000, max(1, int(request.args.get("limit", 1000))))
    return repository.list(
        q=q,
        source=source,
        include_hidden=include_hidden,
        include_tried=include_tried,
        offset=0,
        limit=limit,
    )


@app.get("/api/export.json")
def api_export_json():
    items = _filtered_items_for_export()
    return jsonify({"items": items, "generated_at": datetime.now(timezone.utc).isoformat()})


@app.get("/api/export.csv")
def api_export_csv():
    items = _filtered_items_for_export()
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "code",
            "source",
            "source_title",
            "url",
            "example_text",
            "discovered_at",
            "tried",
            "hidden",
        ],
    )
    writer.writeheader()
    for item in items:
        writer.writerow(item)
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="sora_invite_codes.csv",
    )


@app.get("/api/logs/tail")
def api_logs_tail():
    name = request.args.get("name", "app")
    lines = min(1000, max(1, int(request.args.get("lines", 200))))
    file_path = LOG_FILES.get(name)
    if not file_path or not file_path.exists():
        return jsonify({"ok": False, "error": "unknown_log"}), 404
    with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
        tail_lines = deque(handle, maxlen=lines)
    return jsonify({"ok": True, "lines": list(tail_lines)})


@app.get("/api/sources/health")
def api_sources_health():
    return jsonify({"sources": health_checker.get_statuses()})


@app.post("/api/sources/recheck")
def api_sources_recheck():
    statuses = health_checker.recheck()
    return jsonify({"sources": statuses})


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
from collections import deque

atexit.register(shutdown)

if __name__ == "__main__":
    APP_LOGGER.info(
        "Application starting",
        extra={"component": "startup", "extras": {"url": f"http://{DEFAULT_BIND}:{DEFAULT_PORT}"}},
    )
    app.run(host=DEFAULT_BIND, port=DEFAULT_PORT)
