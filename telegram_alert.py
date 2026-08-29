"""
Sends MODI7's matched news/filing items (NSE announcements, SEBI circulars,
RSS) to Telegram. Meant to run on a schedule (see run_telegram_alert.bat),
independent of whether the Streamlit dashboard is open.

Alerts on every matched item, not just red flags -- events.get_matched_events()
already filters to items that hit at least one of the symbol/macro/positive/
red-flag keyword lists, so "everything matched" here is still a filtered
signal, not the raw firehose. Dedup is handled by events_store's alerted_at
column: each item is only ever alerted once, regardless of how many times
this script runs.
"""

import sys
from datetime import datetime

# Same fix as MODI3's news_alert.py: redirected stdout defaults to a non-UTF-8
# codepage on Windows, which crashes on non-ASCII characters in news titles.
sys.stdout.reconfigure(encoding="utf-8")

from events import get_matched_events
import events_store
from send_telegram import send_telegram_message

MAX_MESSAGE_CHARS = 3500  # Telegram hard-caps messages at 4096 chars


def _format_alert(event):
    tag = "\U0001F534 RED FLAG" if event["is_red_flag"] else "\U0001F4F0"
    tags = ", ".join(event["symbols"] + event["macro_terms"] + event["positive_terms"] + event["red_flag_terms"])
    lines = [f"[MODI7] {tag} <b>{event['source']}</b>", event["title"]]
    if tags:
        lines.append(f"Matched: {tags}")
    lines.append(event["link"])
    return "\n".join(lines)


def _chunk_messages(alert_texts):
    chunks, current_chunk, current_len = [], [], 0
    for text in alert_texts:
        if len(text) > MAX_MESSAGE_CHARS:
            text = text[:MAX_MESSAGE_CHARS] + "... [truncated]"
        if current_len + len(text) + 2 > MAX_MESSAGE_CHARS and current_chunk:
            chunks.append(current_chunk)
            current_chunk, current_len = [], 0
        current_chunk.append(text)
        current_len += len(text) + 2
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def run():
    print(f"\n===== RUN: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====")
    get_matched_events(use_cache=False)  # fetches + classifies + persists to modi7_events.db

    new_events = events_store.get_unalerted_events()
    print(f"{len(new_events)} new item(s) to alert.")

    if not new_events:
        return

    alert_texts = [_format_alert(e) for e in new_events]
    chunks = _chunk_messages(alert_texts)

    total_sent_ok = True
    for chunk in chunks:
        sent = send_telegram_message("\n\n".join(chunk))
        if not sent:
            total_sent_ok = False

    # Mark alerted regardless of per-chunk send success, same tradeoff as
    # MODI3's news_alert.py -- avoids a persistent Telegram outage causing
    # the same backlog to be resent (and re-chunked) every run.
    events_store.mark_alerted([e["id"] for e in new_events])
    print(f"Sent {len(new_events)} new alert(s) in {len(chunks)} message(s). Telegram sent: {total_sent_ok}")


if __name__ == "__main__":
    run()
