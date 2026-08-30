# MODI7 — Company Fundamentals, Red Flags & AI View

A Streamlit dashboard for researching NSE-listed companies: valuation/growth
fundamentals, peer comparison, NSE/SEBI/RSS news with keyword-based red-flag
detection, and an AI-generated sentiment/red-flag summary.

## Setup

```bash
pip install -r requirements.txt
```

### Required: Telegram bot credentials (for alerting)

`send_telegram.py` is **not** committed to this repo — it holds a live bot
token and is gitignored. To enable Telegram alerts (`telegram_alert.py`),
create it yourself in the project root:

```python
import requests

BOT_TOKEN = "your-bot-token-here"
CHAT_ID = "your-chat-id-here"

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    response = requests.post(url, data=payload)
    if response.status_code != 200:
        print(f"Telegram send failed: {response.text}")
    return response.status_code == 200
```

Get a bot token from [@BotFather](https://t.me/BotFather) on Telegram, and
your chat ID by messaging your bot once and checking
`https://api.telegram.org/bot<TOKEN>/getUpdates`.

### Optional: AI View (Phase 3)

The "Generate AI View" button needs at least one LLM credential set as an
environment variable. It tries Claude first and automatically falls back to
Gemini if Claude fails (no credit, no key, rate limit, etc.) — so **one of
the two is enough**, but setting both gives you a working fallback.

| Variable | Where to get it | Used for |
|---|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → Settings → API Keys (needs a funded credit balance) | Claude (tried first) |
| `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (free tier available) | Gemini (fallback) |

On Windows, set a key persistently with:

```powershell
setx ANTHROPIC_API_KEY "your-key-here"
setx GEMINI_API_KEY "your-key-here"
```

**Note:** `setx` only affects new processes — restart your terminal and the
Streamlit dashboard after setting a key for it to take effect.

### Optional: Live intraday charts (Angel One)

The "Today (Live)" chart tab needs a working Angel One SmartAPI login.
`angel_login.py` is **not** committed to this repo (gitignored, like
`send_telegram.py`) since it holds live credentials. Copy your working
version from MODI1's `angel_login.py`, or create one with the same shape:
`CLIENT_ID`, `PASSWORD`, `API_KEY`, `TOTP_SECRET` at the top, and a
module-level `auth_token` set after logging in (see MODI1's `angel_login.py`
for the full login flow).

Also run `python download_angel_scrips.py` once to fetch the NSE instrument
master (`angel_scrips.json`, ~40 MB, gitignored, public Angel One endpoint,
no auth needed) that maps symbols to Angel One's instrument tokens.

Without both files present, the dashboard just skips the "Today (Live)" tab
and shows the yfinance-based daily/weekly/monthly charts only.

## Running

```bash
python -m streamlit run dashboard.py --server.port 8600
```

Then open http://localhost:8600.

## Telegram alerts on a schedule

`run_telegram_alert.bat` runs `telegram_alert.py`, which fetches/classifies
NSE/SEBI/RSS items and sends any not-yet-alerted match to Telegram (tracked
via the `alerted_at` column in `modi7_events.db`, so nothing is ever sent
twice). Register it as a Windows Task Scheduler job to run every 15 minutes
for hands-off alerting.
