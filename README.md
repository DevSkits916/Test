# Sora Invite Code Hunter

https://test-jzhl.onrender.com



Sora Invite Code Hunter continuously monitors curated public sources for potential Sora 2 invite
codes. It normalises feeds from Reddit, X/Twitter, RSS, and generic HTML pages, applies strict
heuristics to extract invite-like tokens, persists the results, and surfaces them through a live
Flask dashboard, JSON API, and export tooling. URL health checks, structured logging, and optional
Discord notifications keep operations observable and production ready.

## Features

- 🔍 **Multi-source adapters** for Reddit searches, subreddit streams, Twitter/X live searches,
  generic RSS feeds, and arbitrary HTML pages.
- 🧭 **URL verification** at startup and on demand with a public health API.
- 🧠 **Robust detection heuristics** including regex length bounds, digit requirement, denylist,
  repeated-character filtering, and ascending sequence rejection.
- 🗄️ **Flexible storage** via an in-memory repository or SQLite persistence with identical APIs.
- 📡 **JSON API + SSE** for programmatic access, live updates, filters, paging, and exports.
- 📊 **Professional UI** with KPIs, filters, SSE-driven updates, source health, logs, and exports.
- 📈 **Structured logging** to stdout and rotating files for app, poller, and source health.
- 🔔 **Optional Discord webhooks** when new invite code candidates are discovered.

## Quick Start

### Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Visit <http://0.0.0.0:3000> for the dashboard and <http://0.0.0.0:3000/healthz> for the health
check.

### Replit

The repository includes `.replit` and `replit.nix`. Import the project on Replit and press **Run**
(the default command executes `python app.py`).

### Docker

```bash
docker build -t sora-hunter .
docker run -p 3000:3000 --env PORT=3000 sora-hunter
```

## Configuration

Environment variables control runtime behaviour:

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `3000` | Port for the Flask app. |
| `BIND` | `0.0.0.0` | Bind address. |
| `POLL_INTERVAL_SECONDS` | `60` | Base polling interval per adapter. |
| `USER_AGENT` | `sora-hunter/0.1` | User-Agent header for outbound requests. |
| `STORE` | `memory` | `memory` (default) or `sqlite`. |
| `SQLITE_PATH` | `data/codes.db` | SQLite database path when `STORE=sqlite`. |
| `DISCORD_WEBHOOK_URL` | _unset_ | Discord webhook for notifications. |
| `MIN_LEN` | `5` | Minimum invite code length. |
| `MAX_LEN` | `8` | Maximum invite code length. |
| `ADAPTERS` | _all adapters_ | Comma-separated adapter list to enable. |

The curated source definitions live in `config/sources.json` and the denylist tokens in
`config/denylist.json`. Both files are loaded and validated at startup; malformed JSON terminates the
app early with an informative log entry.

## API Overview

All endpoints return JSON unless stated otherwise.

| Endpoint | Method | Description |
| --- | --- | --- |
| `/` | GET | Dashboard UI. |
| `/healthz` | GET | Simple health check `{ "ok": true }`. |
| `/events` | GET | Server-Sent Events stream for new codes. |
| `/api/snapshot` | GET | Summary of totals, health info, and latest codes. |
| `/api/codes` | GET | Paginated list with `q`, `source`, `include_hidden`, `include_tried`, `page`, `page_size`. |
| `/api/codes/{code}/tried` | POST | Mark a candidate as tried. |
| `/api/codes/{code}/hide` | POST | Toggle hidden status. |
| `/api/codes/{code}` | DELETE | Delete a candidate. |
| `/api/export.json` | GET | Export filtered candidates as JSON (respects filters). |
| `/api/export.csv` | GET | Export filtered candidates as CSV. |
| `/api/logs/tail` | GET | Tail structured logs (`name=app|poller|source_health`, `lines=N`). |
| `/api/sources/health` | GET | Current status of configured URLs. |
| `/api/sources/recheck` | POST | Re-run health checks across all sources. |

## Data Model

The repository schema (SQLite table `candidates`) stores:

```text
id INTEGER PRIMARY KEY
code TEXT UNIQUE
source TEXT
source_title TEXT
url TEXT
example_text TEXT
discovered_at TEXT (ISO-8601)
tried INTEGER DEFAULT 0
hidden INTEGER DEFAULT 0
```

The in-memory repository mirrors the same structure and behaviour. Both implementations expose a
`count_since` helper used for KPI calculations.

## Logging & Observability

Structured logs use the format `ISO | LEVEL | COMPONENT | message | {extras}` and are emitted to
stdout and rotating files inside `logs/`:

- `logs/app.log` – configuration, startup, API notices.
- `logs/poller.log` – adapter fetch outcomes and backoff decisions.
- `logs/source_health.log` – URL verification results.

Use `/api/logs/tail` or the UI Logs tab to inspect recent activity. Poller backoff is capped at 5
minutes and handles HTTP 429 separately.

## Running Tests

```bash
pytest -q
```

The test suite covers extraction heuristics and repository behaviour (both in-memory and SQLite).

## Limitations & Ethics

- HTML scraping of Twitter/X is best-effort and may degrade gracefully when blocked.
- Invite code detection relies on heuristics and may still produce false positives—manual vetting is
  recommended before use.
- Only public information is monitored. Respect rate limits and do not redistribute harvested codes
  commercially.

## License

This project is released under the MIT License. See [LICENSE](LICENSE) for details.
