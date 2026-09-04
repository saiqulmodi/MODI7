"""
Sends MODI7's matched GLOBAL news/RSS items to Telegram. Meant to run on a
schedule (see run_telegram_alert.bat), independent of whether the Streamlit
dashboard is open.

Alerts on every matched item, not just red flags -- events.get_matched_events()
already filters to items that hit at least one of the symbol/macro/positive/
red-flag keyword lists, so "everything matched" here is still a filtered
signal, not the raw firehose. Dedup is handled by events_store's alerted_at
column: each item is only ever alerted once, regardless of how many times
this script runs.

NSE/SEBI corporate-announcement items are still fetched, classified, and
saved to modi7_events.db here (see events.py) -- the dashboard's red-flag
view and AI synthesis still cover them -- but as of 2026-09-04 they're no
longer PUSHED to Telegram from here: MODI3 already pushes corporate news
(NSE/SEBI), and pushing it from both projects was landing as duplicate
Telegram messages for the same announcement. See _is_corporate_source.
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
    tags = ", ".join(
        event["symbols"] + event["macro_terms"] + event["positive_terms"] + event["red_flag_terms"]
        + event["commodity_metal_terms"] + event["daily_throttle_terms"]
    )
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


CORPORATE_SOURCES = {"NSE Corporate Announcements", "SEBI Circulars"}


def _is_corporate_source(event):
    """True if this event came straight from an NSE/SEBI corporate filing --
    MODI3 already pushes these to Telegram (2026-09-04), so MODI7 suppresses
    them here rather than pushing the same announcement twice. Still saved
    to modi7_events.db either way (see events.py), so the dashboard's
    red-flag view is unaffected."""
    return event["source"] in CORPORATE_SOURCES


def _is_commodity_only(event):
    """True if this event should count against the shared commodities daily
    cap -- i.e. it matched daily_throttle_terms (oil/gold/currency) or
    commodity_metal_terms (silver/copper/base metals/zinc/aluminium/nickel/
    lead) and has no genuinely company-specific significance (a watchlist
    symbol, a real corporate announcement, or a red flag). Both keyword sets
    share ONE daily quota (2026-09-04, at the user's request) -- gold, oil,
    currency, and the other metals are all "commodities" from the same
    slow-moving-price-story mold, so a second metal crossing the wire the
    same day doesn't need its own separate alert either.

    macro_terms is deliberately NOT treated as an exemption here: almost
    every real oil/gold headline also contains a generic macro word
    ("geopolitical", "inflation", "fed rate", "china", "war", etc. are the
    normal context macro/commodity news gets reported in), so exempting on
    macro_terms defeated the cap on nearly every real article -- 20+
    separate oil/gold/silver alerts got sent in a single day instead of
    one, which is what this function is supposed to prevent."""
    return bool(event["daily_throttle_terms"] or event["commodity_metal_terms"]) and not (
        event["symbols"] or event["positive_terms"] or event["red_flag_terms"]
    )


def run():
    print(f"\n===== RUN: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====")
    get_matched_events(use_cache=False)  # fetches + classifies + persists to modi7_events.db

    new_events = events_store.get_unalerted_events()
    print(f"{len(new_events)} new item(s) to alert.")

    if not new_events:
        return

    # Corporate-source items (NSE/SEBI) are suppressed here entirely --
    # MODI3 pushes those. Commodity-only items (oil/gold/currency/metals)
    # are capped at one alert per day: send at most the first one from this
    # run (if today's quota isn't already used), and silently mark any
    # others alerted so they don't pile up and get sent tomorrow instead --
    # a day-old commodity price headline isn't worth surfacing late. Both
    # groups still get mark_alerted (never resent), just not pushed here.
    commodity_quota_used = events_store.daily_commodity_quota_used_today()
    to_send, corporate_suppressed_ids, commodity_suppressed_ids = [], [], []
    for event in new_events:
        if _is_corporate_source(event):
            corporate_suppressed_ids.append(event["id"])
            continue
        if _is_commodity_only(event):
            if commodity_quota_used:
                commodity_suppressed_ids.append(event["id"])
                continue
            commodity_quota_used = True
        to_send.append(event)

    if corporate_suppressed_ids:
        print(f"{len(corporate_suppressed_ids)} NSE/SEBI corporate item(s) suppressed (pushed via MODI3 instead).")
        events_store.mark_alerted(corporate_suppressed_ids)
    if commodity_suppressed_ids:
        print(f"{len(commodity_suppressed_ids)} commodity item(s) suppressed, daily quota already used.")
        events_store.mark_alerted(commodity_suppressed_ids)

    new_events = to_send
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
