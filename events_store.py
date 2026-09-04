"""
SQLite persistence for Phase 2 matched news/filing items -- turns the news
feed from a live-only snapshot (whatever NSE/SEBI/RSS happen to be serving
right now) into a queryable history across days. Each item is deduped by
its source id, tagged with when MODI7 first saw it (first_seen_at), since
the sources themselves don't guarantee a stable "published" timestamp
format across NSE/SEBI/RSS.
"""

import sqlite3
import time
from datetime import datetime

DB_PATH = "modi7_events.db"

_COLUMNS = [
    "id", "source", "published", "title", "link", "symbols",
    "macro_terms", "positive_terms", "red_flag_terms", "is_red_flag", "first_seen_at",
    "alerted_at", "commodity_metal_terms", "daily_throttle_terms",
]


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            source TEXT,
            published TEXT,
            title TEXT,
            link TEXT,
            symbols TEXT,
            macro_terms TEXT,
            positive_terms TEXT,
            red_flag_terms TEXT,
            is_red_flag INTEGER,
            first_seen_at REAL,
            alerted_at REAL
        )
    """)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    if "alerted_at" not in existing_cols:
        conn.execute("ALTER TABLE events ADD COLUMN alerted_at REAL")
    if "commodity_metal_terms" not in existing_cols:
        conn.execute("ALTER TABLE events ADD COLUMN commodity_metal_terms TEXT")
    if "daily_throttle_terms" not in existing_cols:
        conn.execute("ALTER TABLE events ADD COLUMN daily_throttle_terms TEXT")
    return conn


def save_events(items):
    """Inserts new items, silently skipping ones already seen (same id)."""
    conn = _connect()
    now = time.time()
    with conn:
        for item in items:
            conn.execute(
                """INSERT OR IGNORE INTO events
                   (id, source, published, title, link, symbols, macro_terms, positive_terms, red_flag_terms, is_red_flag, first_seen_at, commodity_metal_terms, daily_throttle_terms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(item["id"]), item["source"], item["published"], item["title"], item["link"],
                    ",".join(item["symbols"]), ",".join(item["macro_terms"]),
                    ",".join(item["positive_terms"]), ",".join(item["red_flag_terms"]),
                    int(item["is_red_flag"]), now,
                    ",".join(item.get("commodity_metal_terms", [])),
                    ",".join(item.get("daily_throttle_terms", [])),
                ),
            )
    conn.close()


def _row_to_dict(row):
    d = dict(zip(_COLUMNS, row))
    for key in ("symbols", "macro_terms", "positive_terms", "red_flag_terms", "commodity_metal_terms", "daily_throttle_terms"):
        d[key] = d[key].split(",") if d[key] else []
    d["is_red_flag"] = bool(d["is_red_flag"])
    return d


def query_events(symbol=None, red_flags_only=False, since_days=None, limit=500):
    """Returns stored items, newest-first by first_seen_at, optionally filtered."""
    conn = _connect()
    sql = "SELECT * FROM events WHERE 1=1"
    params = []
    if symbol:
        # symbols column is comma-joined -- bracket with commas so e.g. "SPAL"
        # doesn't accidentally match a stored value like "SPALSUMICHEM".
        sql += " AND (',' || symbols || ',') LIKE ?"
        params.append(f"%,{symbol},%")
    if red_flags_only:
        sql += " AND is_red_flag = 1"
    if since_days is not None:
        sql += " AND first_seen_at >= ?"
        params.append(time.time() - since_days * 86400)
    sql += " ORDER BY first_seen_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_row_to_dict(row) for row in rows]


def count_events():
    conn = _connect()
    n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()
    return n


def get_unalerted_events():
    """Returns stored items never sent to Telegram yet, oldest first (so alert
    order matches original publish order rather than fetch/insert order)."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM events WHERE alerted_at IS NULL ORDER BY first_seen_at ASC"
    ).fetchall()
    conn.close()
    return [_row_to_dict(row) for row in rows]


def daily_commodity_quota_used_today():
    """
    True if an event tagged with a daily_throttle_terms match (oil, gold,
    currency -- see config.DAILY_THROTTLE_KEYWORDS) OR a commodity_metal_terms
    match (silver, copper, base metals, zinc, aluminium, nickel, lead -- see
    config.COMMODITY_METAL_KEYWORDS) has already been alerted today (local
    calendar day). Both categories share one quota (2026-09-04) -- used to
    cap ALL of them together to at most one Telegram alert per day,
    regardless of how many matching headlines come in or which specific
    commodity they're about.
    """
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    conn = _connect()
    row = conn.execute(
        "SELECT 1 FROM events WHERE "
        "((daily_throttle_terms != '' AND daily_throttle_terms IS NOT NULL) "
        "OR (commodity_metal_terms != '' AND commodity_metal_terms IS NOT NULL)) "
        "AND alerted_at IS NOT NULL AND alerted_at >= ? LIMIT 1",
        (midnight,),
    ).fetchone()
    conn.close()
    return row is not None


def mark_alerted(ids):
    """Stamps the given event ids as alerted so a later run won't resend them."""
    if not ids:
        return
    conn = _connect()
    now = time.time()
    with conn:
        conn.executemany(
            "UPDATE events SET alerted_at = ? WHERE id = ?",
            [(now, str(i)) for i in ids],
        )
    conn.close()
