"""Sora Invite Code Hunter web application - Pro Edition."""

from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

import requests
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_cors import CORS
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------- Configuration ----------------

DEFAULT_QUERY = "Sora invite code OR 'Sora 2 invite' OR 'Sora2 invite'"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 "
    "(SoraInviteHunter/2.0; +https://github.com/Sora-invite-hunter)"
)
DEFAULT_POLL_INTERVAL = 60
DEFAULT_MAX_POSTS = 75
DEFAULT_FAILURE_THRESHOLD = 4
DEFAULT_COOLDOWN_SECONDS = 600
MAX_LOG_ENTRIES = 500
MAX_CANDIDATES = 1000
REQUEST_TIMEOUT = 30
PERSISTENCE_FILE = "codes.json"

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

BASE_REQUEST_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9," "application/json;q=0.8,*/*;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.google.com/",
}

REDDIT_SEARCH_URL = "https://www.reddit.com/search.json"
REDDIT_SUBREDDIT_URL_TEMPLATE = "https://www.reddit.com/r/{subreddit}/new.json"
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
OPENAI_FORUM_LATEST_URL = "https://community.openai.com/latest.json"
BLUESKY_SEARCH_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
X_PROXY_PREFIX = "https://r.jina.ai/"
MASTODON_SEARCH_URL = "https://mastodon.social/api/v2/search"

# Enhanced token pattern - supports various formats
TOKEN_PATTERN = re.compile(r"\\b[A-Z0-9]{6}\\b")

INVITE_KEYWORDS = [
    "invite",
    "code",
    "beta",
    "access",
    "key",
    "token",
    "giveaway",
    "sharing",
    "redeem",
    "signup",
    "whitelist",
    "waitlist",
    "drop",
    "wave",
]

HARD_EXCLUDE = {"HTTP", "HTTPS", "JSON", "XML", "HTML", "STATUS", "ERROR", "STACK"}
CONTEXT_BAD = {"error", "exception", "stack", "debug", "traceback", "csrf", "403", "404"}

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "hunter" + os.urandom(12).hex())
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _build_requests_session() -> requests.Session:
    retry_strategy = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD", "OPTIONS"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_REQUEST_SESSION = _build_requests_session()

ConfigDict = Dict[str, object]


@dataclass
class Candidate:
    """Represents a potential invite code candidate."""

    code: str
    example_text: str
    source_title: str
    url: str
    discovered_at: str
    confidence_score: float = 0.5
    source_type: str = "unknown"


@dataclass
class AppState:
    """Thread-safe application state."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    candidates: deque[Candidate] = field(default_factory=lambda: deque(maxlen=MAX_CANDIDATES))
    seen_codes: set[str] = field(default_factory=set)
    last_poll: Optional[str] = None
    activity_log: deque[Dict[str, str]] = field(default_factory=lambda: deque(maxlen=MAX_LOG_ENTRIES))
    error_count: int = 0
    success_count: int = 0
    worker_thread: Optional[threading.Thread] = None

    def save(self) -> None:
        """Persist codes and seen tokens to disk."""
        try:
            with open(PERSISTENCE_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "candidates": [asdict(c) for c in self.candidates],
                        "seen_codes": list(self.seen_codes),
                    },
                    f,
                    indent=2,
                )
            _log_event("Codes persisted to disk.", "info")
        except Exception as e:
            logger.warning("Failed to save codes: %s", e)

    def load(self) -> None:
        """Restore codes and seen tokens from disk."""
        if not os.path.exists(PERSISTENCE_FILE):
            return
        try:
            with open(PERSISTENCE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self.lock:
                self.candidates = deque(
                    [Candidate(**item) for item in data.get("candidates", [])],
                    maxlen=MAX_CANDIDATES,
                )
                self.seen_codes = set(data.get("seen_codes", []))
            _log_event("Codes loaded from disk.", "info")
        except Exception as e:
            logger.warning("Failed to load codes: %s", e)


state = AppState()
state.load()


class SourceSpec:
    """Definition for a single external source to poll."""

    def __init__(
        self,
        name: str,
        fetcher: Callable[[ConfigDict], List[Dict[str, str]]],
        *,
        enabled: bool = True,
        rate_limit_delay: float = 0.0,
        failure_threshold: int | None = None,
        cooldown_seconds: int | None = None,
    ) -> None:
        self.name = name
        self.fetcher = fetcher
        self.enabled = enabled
        self.rate_limit_delay = rate_limit_delay
        self.last_error: Optional[str] = None
        self.last_success: Optional[str] = None
        self.failure_threshold: int = failure_threshold or DEFAULT_FAILURE_THRESHOLD
        self.cooldown_seconds: int = cooldown_seconds or DEFAULT_COOLDOWN_SECONDS
        self.failure_count: int = 0
        self.cooldown_until: Optional[float] = None
        self.disabled_reason: Optional[str] = None


def _iso_now() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _iso_from_timestamp(timestamp: Optional[float]) -> Optional[str]:
    """Convert a UNIX timestamp to ISO format."""
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _log_event(message: str, level: str = "info") -> None:
    """Store activity log message with timestamp."""
    entry = {"timestamp": _iso_now(), "level": level, "message": message}
    with state.lock:
        state.activity_log.append(entry)


def _read_int_env(name: str, default: int) -> int:
    """Read an integer environment variable, falling back gracefully."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using default %s", name, raw, default)
        _log_event(f"Invalid value for {name}: {raw}. Using default {default}.", "warning")
        return default


def _parse_disabled_sources() -> tuple[str, ...]:
    """Return a tuple of disabled sources configured via environment."""
    raw = os.getenv("DISABLE_SOURCES", "")
    if not raw:
        return tuple()
    items = {piece.strip().lower() for piece in raw.split(",") if piece.strip()}
    return tuple(sorted(items))


def _get_config() -> Dict[str, str | int | tuple[str, ...]]:
    """Read configuration from environment variables."""
    poll_interval = _read_int_env("POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL)
    max_posts = _read_int_env("MAX_POSTS", DEFAULT_MAX_POSTS)
    query = os.getenv("QUERY", DEFAULT_QUERY)
    user_agent = os.getenv("USER_AGENT", DEFAULT_USER_AGENT)
    disabled_sources = _parse_disabled_sources()
    return {
        "poll_interval": max(10, poll_interval),
        "max_posts": max(1, min(max_posts, 100)),
        "query": query,
        "user_agent": user_agent,
        "disabled_sources": disabled_sources,
    }


def _reddit_headers(user_agent: str) -> Dict[str, str]:
    """Generate Reddit-compatible headers."""
    return {
        "User-Agent": user_agent,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.reddit.com/",
    }


def _make_request(
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, str | int]] = None,
    *,
    timeout: int = REQUEST_TIMEOUT,
) -> requests.Response:
    """Make HTTP request with retry logic."""
    merged_headers = {**BASE_REQUEST_HEADERS, **(headers or {})}
    merged_headers.setdefault("Referer", url)
    try:
        response = _REQUEST_SESSION.get(url, params=params, headers=merged_headers, timeout=timeout)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException:
        raise


# ---------------- Source fetchers ----------------

def _fetch_reddit(query: str, config: ConfigDict, *, time_filter: str) -> List[Dict[str, str]]:
    params = {
        "q": query,
        "sort": "new",
        "limit": config["max_posts"],
        "restrict_sr": False,
        "t": time_filter,
    }
    headers = _reddit_headers(config["user_agent"])
    response = _make_request(REDDIT_SEARCH_URL, headers, params)
    payload = response.json()
    items = payload.get("data", {}).get("children", [])
    results: List[Dict[str, str]] = []
    for item in items:
        data = item.get("data", {})
        title = data.get("title", "") or ""
        body = data.get("selftext", "") or ""
        permalink = data.get("permalink") or ""
        url = f"https://www.reddit.com{permalink}" if permalink else data.get("url", "")
        results.append({"title": title, "body": body, "url": url})
    return results


def _fetch_reddit_search(config: ConfigDict) -> List[Dict[str, str]]:
    return _fetch_reddit(str(config["query"]), config, time_filter="day")


def _fetch_reddit_search_for(query: str, config: ConfigDict) -> List[Dict[str, str]]:
    return _fetch_reddit(query, config, time_filter="week")


def _fetch_reddit_subreddit(subreddit: str, config: ConfigDict) -> List[Dict[str, str]]:
    params = {"limit": config["max_posts"]}
    headers = _reddit_headers(config["user_agent"])
    url = REDDIT_SUBREDDIT_URL_TEMPLATE.format(subreddit=subreddit)
    response = _make_request(url, headers, params)
    payload = response.json()
    items = payload.get("data", {}).get("children", [])
    results: List[Dict[str, str]] = []
    for item in items:
        data = item.get("data", {})
        title = data.get("title", "") or ""
        body = data.get("selftext", "") or ""
        permalink = data.get("permalink") or ""
        url = f"https://www.reddit.com{permalink}" if permalink else data.get("url", "")
        results.append({"title": title, "body": body, "url": url})
    return results


def _fetch_x_search(search_url: str, description: str, config: ConfigDict) -> List[Dict[str, str]]:
    proxied_url = f"{X_PROXY_PREFIX}{search_url}"
    headers = {"User-Agent": config["user_agent"]}
    try:
        response = _make_request(proxied_url, headers)
        text_content = response.text[:15000]
        return [{"title": description, "body": text_content, "url": search_url}]
    except Exception:
        return []


def _fetch_bluesky_search(config: ConfigDict) -> List[Dict[str, str]]:
    params = {"q": "Sora invite code", "limit": min(int(config["max_posts"]), 25)}
    headers = {"User-Agent": config["user_agent"]}
    try:
        response = _make_request(BLUESKY_SEARCH_URL, headers, params)
        payload = response.json()
        posts = payload.get("posts", [])
        results: List[Dict[str, str]] = []
        for post in posts:
            record = post.get("record", {})
            text = record.get("text", "")
            author = post.get("author", {}).get("handle", "unknown")
            uri = post.get("uri", "")
            url = ""
            if uri:
                url = f"https://bsky.app/profile/{author}/post/{uri.split('/')[-1]}"
            results.append({"title": f"Bluesky post by @{author}", "body": text, "url": url})
        return results
    except Exception:
        return []


def _fetch_mastodon_search(config: ConfigDict) -> List[Dict[str, str]]:
    params = {"q": "Sora invite", "type": "statuses", "limit": min(int(config["max_posts"]), 20)}
    headers = {"User-Agent": config["user_agent"]}
    try:
        response = _make_request(MASTODON_SEARCH_URL, headers, params)
        payload = response.json()
        statuses = payload.get("statuses", [])
        results: List[Dict[str, str]] = []
        for status in statuses:
            content = status.get("content", "") or ""
            clean_content = re.sub(r"<[^>]+>", "", content)
            account = status.get("account", {}).get("acct", "unknown")
            url = status.get("url", "")
            results.append({"title": f"Mastodon post by @{account}", "body": clean_content, "url": url})
        return results
    except Exception:
        return []


def _fetch_hacker_news(config: ConfigDict) -> List[Dict[str, str]]:
    params = {"query": config["query"], "tags": "story,comment", "hitsPerPage": min(int(config["max_posts"]), 50)}
    try:
        response = _make_request(HN_SEARCH_URL, {}, params)
        payload = response.json()
        hits = payload.get("hits", [])
        results: List[Dict[str, str]] = []
        for hit in hits:
            title = hit.get("title") or hit.get("story_title") or ""
            body = hit.get("story_text") or hit.get("comment_text") or ""
            url = hit.get("url") or hit.get("story_url") or ""
            if not url and hit.get("objectID"):
                url = f"https://news.ycombinator.com/item?id={hit['objectID']}"
            results.append({"title": title, "body": body, "url": url})
        return results
    except Exception:
        return []


def _fetch_openai_forum(config: ConfigDict) -> List[Dict[str, str]]:
    headers = {"User-Agent": config["user_agent"]}
    try:
        response = _make_request(OPENAI_FORUM_LATEST_URL, headers)
        payload = response.json()
        topics = payload.get("topic_list", {}).get("topics", [])
        results: List[Dict[str, str]] = []
        for topic in topics[: int(config["max_posts"])]:
            title = topic.get("title", "") or ""
            excerpt = topic.get("excerpt", "") or ""
            slug = topic.get("slug")
            topic_id = topic.get("id")
            url = ""
            if slug and topic_id is not None:
                url = f"https://community.openai.com/t/{slug}/{topic_id}"
            results.append({"title": title, "body": excerpt, "url": url})
        return results
    except Exception:
        return []


SOURCES: List[SourceSpec] = [
    SourceSpec("Reddit search (configured)", _fetch_reddit_search),
    SourceSpec("Reddit search (Sora invite code)", lambda c: _fetch_reddit_search_for("Sora invite code", c)),
    SourceSpec("Reddit search (Sora beta access)", lambda c: _fetch_reddit_search_for('"Sora" "beta" "access"', c)),
    SourceSpec("Reddit /r/ChatGPT", lambda c: _fetch_reddit_subreddit("ChatGPT", c)),
    SourceSpec("Reddit /r/OpenAI", lambda c: _fetch_reddit_subreddit("OpenAI", c)),
    SourceSpec("Reddit /r/SoraAI", lambda c: _fetch_reddit_subreddit("SoraAI", c)),
    SourceSpec("Reddit /r/artificial", lambda c: _fetch_reddit_subreddit("artificial", c)),
    SourceSpec("X live (Sora invite code)", lambda c: _fetch_x_search("https://x.com/search?q=Sora%20invite%20code&f=live", "Live tweets: Sora invite code", c), rate_limit_delay=1.0),
    SourceSpec("X live (#SoraInvite)", lambda c: _fetch_x_search("https://x.com/search?q=%23SoraInvite&f=live", "Live tweets: #SoraInvite", c), rate_limit_delay=1.0),
    SourceSpec("X live (#SoraAccess)", lambda c: _fetch_x_search("https://x.com/search?q=%23SoraAccess&f=live", "Live tweets: #SoraAccess", c), rate_limit_delay=1.0),
    SourceSpec("Bluesky search", _fetch_bluesky_search, rate_limit_delay=2.0),
    SourceSpec("Mastodon search", _fetch_mastodon_search, rate_limit_delay=2.0),
    SourceSpec("Hacker News", _fetch_hacker_news),
    SourceSpec("OpenAI Community", _fetch_openai_forum),
]


def _calculate_confidence(text: str, token: str) -> float:
    text_lower = text.lower()
    score = 0.4
    keyword_count = sum(1 for kw in INVITE_KEYWORDS if kw in text_lower)
    score += min(keyword_count * 0.12, 0.36)
    if "sora" in text_lower:
        score += 0.18
    if any(word in text_lower for word in CONTEXT_BAD):
        score -= 0.35
    if any(word in text_lower for word in ["expired", "redeemed", "invalid", "used up"]):
        score -= 0.25
    if "```" in text or "<code>" in text:
        score += 0.05
    return max(0.05, min(score, 1.0))


def _extract_tokens(text: str) -> List[str]:
    uppercase_text = text.upper()
    tokens: List[str] = []
    for token in TOKEN_PATTERN.findall(uppercase_text):
        if (any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token) and not any(ex in token for ex in HARD_EXCLUDE)):
            tokens.append(token.strip("-"))
    seen: set[str] = set()
    ordered_tokens: List[str] = []
    for token in tokens:
        if token not in seen:
            ordered_tokens.append(token)
            seen.add(token)
    return ordered_tokens


def _build_example_snippet(title: str, body: str, token: str) -> str:
    combined = f"{title}\\n{body}".strip()
    if not combined:
        return html.escape(title or token)
    match = re.search(re.escape(token), combined, re.IGNORECASE)
    if match:
        start = max(match.start() - 60, 0)
        end = min(match.end() + 60, len(combined))
    else:
        start = 0
        end = min(len(combined), 200)
    snippet = combined[start:end].replace("\\n", " ").strip()
    pattern = re.compile(re.escape(token), re.IGNORECASE)
    highlighted_parts: List[str] = []
    last_end = 0
    for m in pattern.finditer(snippet):
        highlighted_parts.append(html.escape(snippet[last_end:m.start()]))
        highlighted_parts.append(f"<mark>{html.escape(m.group(0))}</mark>")
        last_end = m.end()
    highlighted_parts.append(html.escape(snippet[last_end:]))
    return "".join(highlighted_parts)


def _process_entries(entries: List[Dict[str, str]], source_label: str) -> List[Candidate]:
    new_candidates: List[Candidate] = []
    for entry in entries:
        title = entry.get("title", "") or ""
        body = entry.get("body", "") or ""
        url = entry.get("url", "") or ""
        tokens = _extract_tokens(f"{title}\\n{body}")
        for token in tokens:
            with state.lock:
                if token in state.seen_codes:
                    continue
                state.seen_codes.add(token)
            confidence = _calculate_confidence(f"{title}\\n{body}", token)
            snippet = _build_example_snippet(title, body, token)
            display_title = title or "Untitled"
            if source_label and source_label not in display_title:
                display_title = f"[{source_label}] {display_title}"
            candidate = Candidate(
                code=token,
                example_text=snippet,
                source_title=display_title,
                url=url,
                discovered_at=_iso_now(),
                confidence_score=confidence,
                source_type=source_label.split()[0].lower() if source_label else "unknown",
            )
            with state.lock:
                state.candidates.append(candidate)
            new_candidates.append(candidate)
            _log_event(f"New candidate {token} from {source_label or 'unknown'} (conf={confidence:.2f})", "success")
    return new_candidates


def _poll_sources() -> None:
    while True:
        start_time = time.time()
        config = _get_config()
        disabled_set = {name.lower() for name in config.get("disabled_sources", ())}
        _log_event(f"Starting poll cycle ({len(SOURCES)} sources)", "info")
        cycle_candidates: List[Candidate] = []
        for source in SOURCES:
            if not source.enabled:
                continue
            now = time.time()
            if source.name.lower() in disabled_set:
                if source.disabled_reason != "disabled-by-env":
                    source.disabled_reason = "disabled-by-env"
                    _log_event(f"{source.name} disabled via DISABLE_SOURCES", "info")
                continue
            elif source.disabled_reason == "disabled-by-env":
                source.disabled_reason = None
            if source.cooldown_until:
                if now < source.cooldown_until:
                    if source.disabled_reason != "cooldown":
                        source.disabled_reason = "cooldown"
                        resume_at = _iso_from_timestamp(source.cooldown_until)
                        _log_event(f"{source.name} cooling down until {resume_at}", "info")
                    continue
                source.cooldown_until = None
                source.failure_count = 0
                source.disabled_reason = None
            try:
                entries = source.fetcher(config)
                new_from_source = _process_entries(entries, source.name)
                cycle_candidates.extend(new_from_source)
                source.last_success = _iso_now()
                source.last_error = None
                source.failure_count = 0
                source.disabled_reason = None
                with state.lock:
                    state.success_count += 1
                if source.rate_limit_delay > 0:
                    time.sleep(source.rate_limit_delay)
            except Exception as exc:
                _log_event(f"{source.name}: {exc}", "error")
                source.last_error = _iso_now()
                with state.lock:
                    state.error_count += 1
                source.failure_count += 1
                if source.failure_count >= source.failure_threshold:
                    source.cooldown_until = time.time() + source.cooldown_seconds
                    source.disabled_reason = "cooldown"
                    resume_at = _iso_from_timestamp(source.cooldown_until)
                    _log_event(f"{source.name} paused for {source.cooldown_seconds}s after repeated failures; will resume at {resume_at}", "warning")
                else:
                    source.disabled_reason = "error"
        if cycle_candidates:
            _log_event(f"Discovered {len(cycle_candidates)} new candidates", "success")
        else:
            _log_event("No new candidates this cycle", "info")
        with state.lock:
            state.last_poll = _iso_now()
        elapsed = time.time() - start_time
        sleep_for = max(config["poll_interval"] - elapsed, 5)
        # Persist periodically
        state.save()
        time.sleep(sleep_for)


def _start_background_thread() -> None:
    with state.lock:
        if state.worker_thread and state.worker_thread.is_alive():
            return
        thread = threading.Thread(target=_poll_sources, name="source-poller", daemon=True)
        thread.start()
        state.worker_thread = thread
    _log_event("System initialized", "info")


# ---------------- Routes ----------------

@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/codes.json")
def codes_json():
    config = _get_config()
    disabled_set = {name.lower() for name in config.get("disabled_sources", ())}
    with state.lock:
        candidates = [asdict(c) for c in reversed(state.candidates)]
        activity_log = list(reversed(state.activity_log))
        snapshot = {
            "query": config["query"],
            "poll_interval_seconds": config["poll_interval"],
            "max_posts": config["max_posts"],
            "disabled_sources": list(config.get("disabled_sources", ())),
            "last_poll": state.last_poll,
            "total_candidates": len(state.candidates),
            "unique_codes": len(state.seen_codes),
            "success_count": state.success_count,
            "error_count": state.error_count,
            "candidates": candidates,
            "activity_log": activity_log,
            "sources": [
                {
                    "name": s.name,
                    "enabled": s.enabled,
                    "active": (s.enabled and s.cooldown_until is None and s.name.lower() not in disabled_set),
                    "last_success": s.last_success,
                    "last_error": s.last_error,
                    "failure_count": s.failure_count,
                    "failure_threshold": s.failure_threshold,
                    "cooldown_until": _iso_from_timestamp(s.cooldown_until),
                    "disabled_reason": s.disabled_reason,
                    "rate_limit_delay": s.rate_limit_delay,
                }
                for s in SOURCES
            ],
        }
    return jsonify(snapshot)


@app.route("/healthz")
def healthz():
    config = _get_config()
    disabled_set = {name.lower() for name in config.get("disabled_sources", ())}
    with state.lock:
        thread_alive = bool(state.worker_thread and state.worker_thread.is_alive())
        active_sources = [
            s.name for s in SOURCES if s.enabled and s.cooldown_until is None and s.name.lower() not in disabled_set
        ]
        paused_sources = [
            s.name for s in SOURCES if (s.name.lower() in disabled_set or (not s.enabled) or (s.cooldown_until is not None))
        ]
        payload = {
            "status": "ok" if thread_alive else "degraded",
            "worker_thread_alive": thread_alive,
            "active_sources": active_sources,
            "paused_sources": paused_sources,
            "total_candidates": len(state.candidates),
            "last_poll": state.last_poll,
            "error_count": state.error_count,
        }
    return jsonify(payload), (200 if thread_alive else 503)


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(app.root_path, "static"), "favicon.ico", mimetype="image/x-icon")


# ---------------- Admin (minimal) ----------------

def _is_admin() -> bool:
    return session.get("admin") is True


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))
    if not _is_admin():
        return (
            """
            <html><head><meta name='viewport' content='width=device-width, initial-scale=1'>
            <style>body{font-family:system-ui;margin:2rem}input{padding:.5rem;border:1px solid #ccc;border-radius:6px}</style></head>
            <body><h2>Admin Login</h2>
            <form method="post"><input name="password" placeholder="Password" type="password" />
            <button type="submit">Login</button></form></body></html>
            """,
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    # show toggles
    rows = []
    for i, s in enumerate(SOURCES):
        rows.append(
            f"<tr><td>{html.escape(s.name)}</td>"
            f"<td>{'on' if s.enabled else 'off'}</td>"
            f"<td><form method='post' action='{url_for('toggle_source')}' style='display:inline'>"
            f"<input type='hidden' name='index' value='{i}'/>"
            f"<button type='submit'>{'Disable' if s.enabled else 'Enable'}</button>"
            f"</form></td></tr>"
        )
    page = (
        "<html><head><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<style>body{font-family:system-ui;margin:1rem}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccc;padding:.5rem;text-align:left}</style></head><body>"
        "<h2>Admin</h2><p><a href='/'>← Back</a></p>"
        "<table><thead><tr><th>Source</th><th>Enabled</th><th>Action</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</body></html>"
    )
    return page


@app.route("/admin/toggle", methods=["POST"])
def toggle_source():
    if not _is_admin():
        return redirect(url_for("admin"))
    try:
        idx = int(request.form.get("index", "-1"))
    except ValueError:
        idx = -1
    if 0 <= idx < len(SOURCES):
        SOURCES[idx].enabled = not SOURCES[idx].enabled
        _log_event(f"Admin toggled source: {SOURCES[idx].name} -> {'enabled' if SOURCES[idx].enabled else 'disabled'}", "info")
    return redirect(url_for("admin"))


# ---------------- Startup ----------------

# Start the background worker as soon as the module is imported
def _startup():
    _start_background_thread()


_startup()


def create_app() -> Flask:
    _start_background_thread()
    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", 3000))
    host = os.getenv("HOST", "0.0.0.0")
    try:
        app.run(host=host, port=port)
    finally:
        state.save()
