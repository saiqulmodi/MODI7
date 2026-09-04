"""
One-off validation check for the global-only/daily-throttle commodity alert
filtering added to MODI7 on 2026-09-01 (see config.py's COMMODITY_METAL_KEYWORDS,
DAILY_THROTTLE_KEYWORDS, GLOBAL_SOURCES). Reads modi7_events.db (read-only)
and sends a summary to Telegram -- does not modify any state or resend
anything itself. Meant to run once, a day after the change, via a Windows
Scheduled Task (see run_check_commodity_filter.bat).
"""

import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

import events_store
from config import GLOBAL_SOURCES
from send_telegram import send_telegram_message

recent = events_store.query_events(since_days=1, limit=1000)

commodity_metal_alerts = [e for e in recent if e["commodity_metal_terms"] and e["alerted_at"]]
daily_throttle_alerts = [e for e in recent if e["daily_throttle_terms"] and e["alerted_at"]]

bad_source_leaks = [e for e in commodity_metal_alerts if e["source"] not in GLOBAL_SOURCES]

lines = [f"[MODI7] Commodity filter check -- {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
lines.append(f"Silver/base-metal alerts sent (should all be from global sources): {len(commodity_metal_alerts)}")
if bad_source_leaks:
    lines.append(f"  ⚠️ FILTER FAILED -- {len(bad_source_leaks)} sent from a non-global source:")
    for e in bad_source_leaks[:5]:
        lines.append(f"    [{e['source']}] {e['title']}")
else:
    lines.append("  OK -- no local-source leaks found.")

lines.append(f"\nOil/gold/currency alerts sent (should be 0 or 1 for the day): {len(daily_throttle_alerts)}")
if len(daily_throttle_alerts) > 1:
    lines.append(f"  ⚠️ THROTTLE FAILED -- more than one sent today:")
    for e in daily_throttle_alerts[:5]:
        lines.append(f"    [{e['source']}] {e['title']}")
else:
    lines.append("  OK -- within the daily cap.")

message = "\n".join(lines)
print(message)
sent = send_telegram_message(message)
print(f"\nTelegram sent: {sent}")
