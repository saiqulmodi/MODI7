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

DB_PATH = "modi7_events.db"

_COLUMNS = [
    "id", "source", "published", "title", "link", "symbols",
    "macro_terms", "positive_terms", "red_flag_terms", "is_red_flag", "first_seen_at",
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
            first_seen_at REAL
        )
    """)
    return conn


def save_events(items):
    """Inserts new items, silently skipping ones already seen (same id)."""
    conn = _connect()
    now = time.time()
    with conn:
        for item in items:
            conn.execute(
                """INSERT OR IGNORE INTO events
                   (id, source, published, title, link, symbols, macro_terms, positive_terms, red_flag_terms, is_red_flag, first_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(item["id"]), item["source"], item["published"], item["title"], item["link"],
                    ",".join(item["symbols"]), ",".join(item["macro_terms"]),
                    ",".join(item["positive_terms"]), ",".join(item["red_flag_terms"]),
                    int(item["is_red_flag"]), now,
                ),
            )
    conn.close()


def _row_to_dict(row):
    d = dict(zip(_COLUMNS, row))
    for key in ("symbols", "macro_terms", "positive_terms", "red_flag_terms"):
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
