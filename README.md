# Daft rental bot

Checks daft.ie for new rental listings that match your criteria and sends them to Telegram, with a link and a ready-to-paste enquiry message.

- **Search:** [daftlistings](https://github.com/AnthonyBloomer/daftlistings), installed from GitHub because the PyPI release gets HTTP 403 from daft.ie.
- **Admin page:** http://localhost:8765. Edit criteria and Telegram settings, start/stop the bot, scan now, remember current listings, see matches and the log.
- **Applying:** not automated. daft's enquiry form requires a login and a reCAPTCHA, and daftlistings can only read listings. The bot gives you the link and your message to paste.

## Run

```bash
docker compose up -d --build
```

Settings and state are kept in `./data` and survive restarts and rebuilds. If the bot was running before a restart, it carries on.

## First start

1. Open **Settings**: set your locations, price, beds and filters, then set up Telegram (the steps are on the page) and press **Send test message**.
2. On **Dashboard**, press **Start bot** with "Remember current listings first" ticked. Listings already on daft are stored as seen, so you only get messages for listings posted after that.
3. If you widen your criteria later, tick "Also remember listings that match the new criteria" when saving, or press **Remember all current listings**.

Safety nets: at most *Max messages per scan* are sent per scan, and the rest wait for the next one. A listing is never sent twice.

## GitHub Actions (free, runs without your PC)

`.github/workflows/bot.yml` builds the Docker image and runs one scan every 5 minutes, using `bot-data/settings.json` and `bot-data/state.json` from this repo. When listings are newly remembered, it commits `bot-data/state.json` back.

- **Secrets** (Settings → Secrets and variables → Actions): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- **Admin page:** `docs/` is a static page served by GitHub Pages (Settings → Pages → Deploy from a branch → `main` / `/docs`), at `https://<user>.github.io/daft-bot/`. Sign in with a fine-grained token for this repo only, with **Actions** and **Contents** read/write. The page edits `bot-data/settings.json` (criteria, message, start/stop) and starts `scan`/`remember` runs.
- **Without the admin page:** edit `bot-data/settings.json` (`"running"` starts/stops scheduled scans), and use Actions → daft-bot → Run workflow.
- The repo is public, so don't put private details in settings; the Telegram token stays in Secrets.
- Run either GitHub Actions or the local Docker bot, not both, or you'll get every message twice.

## Options (.env)

| Variable | Purpose |
|---|---|
| `ADMIN_PASSWORD` | Password-protects the admin page (any username). Set this before exposing the page to the internet. |
| `ADMIN_PORT` | Host port, default 8765 |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Used when they are not set on the Settings page |

## Tests

Tests run during `docker compose build`.
