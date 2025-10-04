# Sora Invite Hunter Pro (Render-ready)

A Flask web app that monitors multiple sources (Reddit, X/Twitter via proxy, Bluesky, Mastodon, Hacker News, and the OpenAI Community forum) for possible "Sora invite codes." It extracts token-shaped strings, scores them by context, and shows them in a live UI with copy-to-clipboard, activity logs, and source health. Includes an admin panel to enable/disable sources on the fly.

## Features
- Multi-source polling with retry/cooldown backoff
- Mobile-friendly UI with dark mode support
- Copy-to-clipboard buttons for each candidate code
- Activity log + stats cards
- `/healthz` endpoint for Render health checks
- Simple persistence (`codes.json`) to survive restarts
- Minimal password-protected admin panel (`/admin`) for toggling sources (password via `ADMIN_PASSWORD`)

> **Note**: This app looks for *candidate* tokens. It cannot guarantee validity of any code.

## Deploy on Render
1. **Create a new Web Service** on Render and point it to this repo.
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `gunicorn sora_invite:app -b 0.0.0.0:$PORT`
4. Environment (optional):
   - `FLASK_SECRET_KEY` (random string)
   - `ADMIN_PASSWORD` (default: `admin`)
   - `POLL_INTERVAL_SECONDS` (default: 60)
   - `MAX_POSTS` (default: 75)
   - `QUERY` (default: *see .env.example*)
   - `DISABLE_SOURCES` (comma-separated names to disable sources)
5. (Optional) Health check path: `/healthz`

## Local Run
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PORT=3000
python sora_invite.py
# visit http://localhost:3000
```

## Docker (optional)
```bash
docker build -t sora-invite .
docker run -p 3000:3000 sora-invite
```

## Admin Panel
Visit `/admin`. Default password is `admin` (set via `ADMIN_PASSWORD`).
You can:
- Toggle sources on/off (applies immediately)
- See state of each source at a glance

## File structure
```
SoraInviteHunterPro/
├── sora_invite.py
├── templates/
│   └── index.html
├── static/
│   └── favicon.ico
├── requirements.txt
├── Procfile
├── Dockerfile
├── .env.example
└── README.md
```

## License
MIT
