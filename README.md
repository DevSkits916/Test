# Sora Invite Code Hunter

Sora Invite Code Hunter is a lightweight monitoring tool that keeps an eye on public sources for posts that might contain invite codes for OpenAI's Sora program. It continuously polls Reddit, RSS feeds, and arbitrary HTML pages, extracts strings that look like invite codes, deduplicates them, and serves them through a live dashboard, JSON API, and optional Discord notifications.

## Features

- 🔍 **Multi-source polling** with pluggable adapters (Reddit search, subreddit feeds, RSS/Atom, generic HTML pages).
- 🧠 **Heuristic extraction** using regex, length checks, and a configurable denylist to reduce false positives.
- 🗄️ **Storage abstraction** with fast in-memory mode and optional SQLite persistence.
- 🔁 **Background scheduler** that keeps polling without blocking the web server and gracefully handles HTTP errors and rate limits.
- 📊 **Real-time dashboard** with Server-Sent Events (SSE) that streams new codes without a page refresh.
- 📡 **JSON API** for programmatic access, including pagination, filters, and state-changing endpoints.
- 🔔 **Optional Discord notifications** whenever a new candidate code is discovered.
- 📦 **Deploy anywhere** with simple Python dependencies, Dockerfile, and Replit configuration.

## Quickstart

### Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The server listens on `http://0.0.0.0:3000` by default. Visit the dashboard at `/` and the health check at `/healthz`.

### Docker

```bash
docker build -t sora-hunter .
docker run -p 3000:3000 --env PORT=3000 sora-hunter
```

### Replit

The repository includes `.replit` and `replit.nix`. Import the project on Replit and click **Run**.

## Deployment on Render.com

1. Create a new **Web Service** in Render and connect this repository.
2. Set **Environment** to `Docker` and keep the Dockerfile defaults.
3. Configure environment variables as needed (see below). Render automatically installs dependencies and runs `python app.py`.
4. If using SQLite persistence, set `STORE=sqlite` and ensure the `data/` directory is writable (Render's persistent disk).

## Configuration

Environment variables control runtime behavior:

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `3000` | Port the Flask server binds to. |
| `BIND` | `0.0.0.0` | Bind address. |
| `POLL_INTERVAL_SECONDS` | `60` | Interval between polling cycles. |
| `USER_AGENT` | `SoraInviteCodeHunter/1.0 (+https://render.com/docs/deploy-flask)` | User agent string for HTTP requests. |
| `STORE` | `memory` | Storage backend: `memory` or `sqlite`. |
| `SQLITE_PATH` | `data/codes.db` | SQLite file path when `STORE=sqlite`. |
| `DISCORD_WEBHOOK_URL` | _(unset)_ | Discord webhook to notify about new codes. |
| `ADAPTERS` | `reddit_search,reddit_subs,generic_rss,generic_html` | Comma-separated list of adapters to enable. |

> **Reddit 403 errors:** Reddit increasingly rejects requests without a descriptive user agent. Update `USER_AGENT` to include a
> contact URL/email you control (for example `SoraInviteCodeHunter/1.0 (+https://example.com/contact)`). The built-in Reddit
> adapters automatically retry through `api.reddit.com` if `www.reddit.com` responds with HTTP 403, which keeps polling running
> on providers such as Render.

Adapter-specific settings and denylist tokens live in `config/sources.json`:

```json
{
  "reddit_search": {
    "query": "Sora invite code OR \"Sora 2 invite\" OR \"Sora2 invite\"",
    "limit": 75
  },
  "reddit_subs": {
    "subs": ["ChatGPT", "OpenAI", "SoraAI"],
    "limit": 50
  },
  "generic_rss": {
    "feeds": [
      "https://hnrss.org/newest",
      "https://news.ycombinator.com/rss"
    ]
  },
  "generic_html": {
    "urls": [
      "https://www.reddit.com/r/ChatGPT/",
      "https://www.reddit.com/r/OpenAI/",
      "https://www.reddit.com/r/SoraAI/"
    ]
  },
  "denylist_tokens": ["TODAY", "UPDATE", "HTTPS", "HTTP", "AM", "PM", "UTC", "USA", "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "SEPT", "OCT", "NOV", "DEC"]
}
```

Adjust values as needed, redeploy, and the polling thread will use the new configuration.

## API

| Endpoint | Method | Description |
| --- | --- | --- |
| `/` | GET | Dashboard UI. |
| `/api/snapshot` | GET | Latest poll timestamp, counts, and most recent candidates. |
| `/api/codes` | GET | Paginated list with filters: `q`, `source`, `include_hidden`, `include_tried`, `page`, `page_size`. |
| `/api/codes/<code>/tried` | POST | Mark a code as tried. |
| `/api/codes/<code>/hide` | POST | Toggle hidden flag. |
| `/api/codes/<code>` | DELETE | Delete a candidate. |
| `/events` | GET | Server-Sent Events stream with new candidates. |
| `/healthz` | GET | Health check returning `{ "ok": true }`. |

### Candidate payload

```json
{
  "code": "7ZDCNP",
  "source": "reddit_search",
  "source_title": "Sora invite drop",
  "url": "https://www.reddit.com/...",
  "example_text": "Sharing my spare Sora invite...",
  "discovered_at": "2024-03-11T14:33:22Z",
  "tried": 0,
  "hidden": 0
}
```

## Tests

Run the unit tests with:

```bash
pytest -q
```

Tests cover the extractor logic and both storage backends, plus a minimal integration check for the health endpoint.

## Ethics and rate limits

The app only polls public endpoints and respects published rate limits. Be mindful of the load you generate, customize polling intervals responsibly, and never use the tool for commercial resale of invite codes.

## Roadmap

- Optional authentication for write endpoints.
- UI for editing adapter configuration.
- Additional source adapters (e.g., Mastodon, Bluesky).
- Advanced heuristics using NLP for fewer false positives.

## License

MIT © 2024 [Your Name]
