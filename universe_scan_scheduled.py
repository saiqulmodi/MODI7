"""
Scheduled background scan for MODI7's MODI1 intraday universe -- keeps a
combined trend-category + fundamentals snapshot on disk so the dashboard can
show grouped-by-category results instantly instead of requiring a live
15-20 minute scan every time someone opens it.

Two modes, meant to run on different schedules (see run_universe_trend_scan.bat
/ run_universe_fundamentals_scan.bat and the MODI7_TrendScan /
MODI7_FundamentalsScan_* Task Scheduler jobs):

  --mode trend    Fast pass (~2-4 min, 1 Yahoo call/symbol). Refreshes each
                   symbol's trend category only. Meant to run every 30 min
                   since price moves throughout the trading day.

  --mode full      Slow pass (~15-20 min, 5+ Yahoo calls/symbol). Refreshes
                   fundamentals only (categories are left to the trend-mode
                   job, so the two never double up on Yahoo calls in the same
                   run). Meant to run only a few times a day -- fundamentals
                   (P/E, ROE, growth) don't move intraday, so scanning them as
                   often as the trend pass would just add unnecessary Yahoo
                   request volume for no new information.

Both modes merge into the same snapshot file (SNAPSHOT_PATH) rather than
overwriting it, so a trend-only run never wipes out the last full run's
fundamentals data, and vice versa.

Every trend pass also compares each symbol's new category against what was
stored from the previous pass and Telegram-alerts on any change (SMA tier,
EMA tier, or both) -- alerts only, no auto-trading, matching how MODI1's
alerting works. A symbol's first-ever categorization doesn't alert (there's
no prior category to have "changed" from).
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

from universe import MODI1_INTRADAY_SYMBOLS
from trend_category import get_bulk_trend_categories
from fundamentals import get_bulk_fundamentals
from send_telegram import send_telegram_message

SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "universe_scan_snapshot.json")

# Same 4096-char Telegram cap as telegram_alert.py's MAX_MESSAGE_CHARS, with
# the same safety margin.
_MAX_MESSAGE_CHARS = 3500


def load_snapshot():
    if os.path.exists(SNAPSHOT_PATH):
        with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"trend_updated_at": None, "fundamentals_updated_at": None, "symbols": {}}


def _save_snapshot(snapshot):
    # Write-then-rename so a reader (the dashboard) never sees a half-written
    # file if it happens to read while this script is mid-save.
    tmp_path = SNAPSHOT_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    os.replace(tmp_path, SNAPSHOT_PATH)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _format_transition(t):
    parts = []
    if t["sma_changed"]:
        parts.append(f"SMA {t['old_category']} -> {t['new_category']}")
    if t["ema_changed"]:
        parts.append(f"EMA {t['old_ema_category']} -> {t['new_ema_category']}")
    price = f" @ {t['last_close']}" if t.get("last_close") is not None else ""
    return f"[MODI7] {t['symbol']}{price}: " + ", ".join(parts)


def _chunk_messages(texts):
    chunks, current, current_len = [], [], 0
    for text in texts:
        if current_len + len(text) + 1 > _MAX_MESSAGE_CHARS and current:
            chunks.append(current)
            current, current_len = [], 0
        current.append(text)
        current_len += len(text) + 1
    if current:
        chunks.append(current)
    return chunks


def _send_category_change_alerts(transitions):
    texts = [_format_transition(t) for t in transitions]
    chunks = _chunk_messages(texts)
    total_sent_ok = True
    for chunk in chunks:
        if not send_telegram_message("\n".join(chunk)):
            total_sent_ok = False
    print(
        f"[{_now_iso()}] Sent {len(transitions)} category-change alert(s) in {len(chunks)} "
        f"message(s). Telegram sent: {total_sent_ok}",
        flush=True,
    )


def run_trend_pass():
    snapshot = load_snapshot()
    print(f"[{_now_iso()}] Trend pass: categorizing {len(MODI1_INTRADAY_SYMBOLS)} symbols...", flush=True)
    results = get_bulk_trend_categories(MODI1_INTRADAY_SYMBOLS)

    transitions = []
    for symbol, result in zip(MODI1_INTRADAY_SYMBOLS, results):
        entry = snapshot["symbols"].setdefault(symbol, {})
        if result.get("error"):
            entry["trend_error"] = result["error"]
            entry.pop("category", None)
            entry.pop("ema_category", None)
            entry.pop("trend", None)
            continue

        old_category = entry.get("category")
        old_ema_category = entry.get("ema_category")

        entry["category"] = result["category"]
        entry["ema_category"] = result["ema_category"]
        entry["trend"] = {k: v for k, v in result.items() if k != "error"}
        entry.pop("trend_error", None)

        # None means this symbol has never been categorized before -- not a
        # "change", just the first observation, so don't alert on it.
        sma_changed = old_category is not None and old_category != result["category"]
        ema_changed = old_ema_category is not None and old_ema_category != result["ema_category"]
        if sma_changed or ema_changed:
            transitions.append({
                "symbol": symbol,
                "old_category": old_category, "new_category": result["category"], "sma_changed": sma_changed,
                "old_ema_category": old_ema_category, "new_ema_category": result["ema_category"],
                "ema_changed": ema_changed,
                "last_close": result.get("last_close"),
            })

    snapshot["trend_updated_at"] = _now_iso()
    _save_snapshot(snapshot)
    ok = sum(1 for r in results if not r.get("error"))
    print(f"[{_now_iso()}] Trend pass done: {ok}/{len(results)} categorized.", flush=True)

    if transitions:
        _send_category_change_alerts(transitions)
    else:
        print(f"[{_now_iso()}] No category changes since the last pass.", flush=True)


def run_full_pass():
    """Fundamentals only -- categories are refreshed by the separate
    trend-mode job, so this doesn't re-run that (would double the Yahoo
    request volume for no benefit, and risks the two passes overlapping and
    hitting Yahoo concurrently from two processes at once)."""
    snapshot = load_snapshot()

    print(
        f"[{_now_iso()}] Full pass: fetching fundamentals for {len(MODI1_INTRADAY_SYMBOLS)} symbols "
        f"(this is the slow part, 15-20+ min)...",
        flush=True,
    )
    fund_results = get_bulk_fundamentals(MODI1_INTRADAY_SYMBOLS)
    for symbol, result in zip(MODI1_INTRADAY_SYMBOLS, fund_results):
        entry = snapshot["symbols"].setdefault(symbol, {})
        if result.get("error"):
            entry["fundamentals_error"] = result["error"]
            entry.pop("fundamentals", None)
        else:
            entry["fundamentals"] = {k: v for k, v in result.items() if k != "error"}
            entry.pop("fundamentals_error", None)

    snapshot["fundamentals_updated_at"] = _now_iso()
    _save_snapshot(snapshot)
    ok = sum(1 for r in fund_results if not r.get("error"))
    print(f"[{_now_iso()}] Full pass done: {ok}/{len(fund_results)} fundamentals fetched.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["trend", "full"], required=True)
    args = parser.parse_args()

    start = time.time()
    if args.mode == "trend":
        run_trend_pass()
    else:
        run_full_pass()
    print(f"[{_now_iso()}] Finished in {time.time() - start:.0f}s.", flush=True)
