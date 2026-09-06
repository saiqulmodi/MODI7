"""
Reads C:\\Users\\saiqu\\alerts_digest\\alerts_log.jsonl -- the shared log every
MODI project's send_telegram.py now appends to on every alert it actually
sends -- and sends one consolidated "here's what fired today" digest.

This organizes and relays what each alert itself already said (its own
signal, numbers, and reasoning). It does not add trading advice, a buy/sell
opinion, or a recommendation of its own -- that call is yours, this is just
everything in one place instead of scattered across each project's own
Telegram messages throughout the day.

Meant to run once a day, after market close (see register_daily_digest.ps1
for the Task Scheduler job -- 4:00 PM IST, weekdays).
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

import requests
from send_telegram import BOT_TOKEN, CHAT_ID


def _send_digest_raw(text):
    """Sends the digest via a direct API call rather than
    send_telegram.send_telegram_message(), which auto-logs every message it
    sends to the same alerts_log.jsonl this script reads from -- using it
    here would make the digest include itself as one of "today's alerts",
    growing self-referentially on every re-run."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    response = requests.post(url, data=payload)
    if response.status_code != 200:
        print(f"Telegram send failed: {response.text}")
    return response.status_code == 200

ALERTS_LOG_PATH = r"C:\Users\saiqu\alerts_digest\alerts_log.jsonl"


def load_todays_alerts(target_date=None):
    target_date = target_date or datetime.now().date()
    alerts = []
    if not os.path.exists(ALERTS_LOG_PATH):
        return alerts
    with open(ALERTS_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry_date = datetime.fromisoformat(entry["timestamp"]).date()
            if entry_date == target_date:
                alerts.append(entry)
    return alerts


def build_digest(alerts, target_date):
    if not alerts:
        return (
            f"<b>Daily Alert Digest -- {target_date.strftime('%Y-%m-%d')}</b>\n\n"
            f"No alerts were sent by any MODI project today."
        )

    by_project = defaultdict(list)
    for entry in alerts:
        by_project[entry["project"]].append(entry)

    lines = [f"<b>Daily Alert Digest -- {target_date.strftime('%Y-%m-%d')}</b>"]
    lines.append(f"{len(alerts)} alert(s) across {len(by_project)} project(s) today.\n")

    for project in sorted(by_project):
        entries = sorted(by_project[project], key=lambda e: e["timestamp"])
        lines.append(f"--- {project} ({len(entries)}) ---")
        for entry in entries:
            time_str = datetime.fromisoformat(entry["timestamp"]).strftime("%H:%M")
            # First line of the original alert text only -- the full alert
            # (with all its own reasoning/numbers) is still in that
            # project's own Telegram history if you want the detail; this
            # digest is an index into that, not a replacement for it.
            first_line = entry["message"].split("\n", 1)[0]
            lines.append(f"  {time_str} -- {first_line}")
        lines.append("")

    lines.append(
        "This is a summary of what each alert already said -- no advice or "
        "recommendation added. Full detail for any line is in that "
        "project's own Telegram messages earlier today."
    )
    return "\n".join(lines)


def main():
    target_date = datetime.now().date()
    alerts = load_todays_alerts(target_date)
    digest = build_digest(alerts, target_date)
    print(digest)
    sent = _send_digest_raw(digest)
    print(f"\nDigest sent: {sent}")


if __name__ == "__main__":
    main()
