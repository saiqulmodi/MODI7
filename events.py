"""
Phase 2 event aggregator: pulls NSE corporate announcements, SEBI circulars,
and financial-news RSS feeds, classifies each item against the MODI1
watchlist + macro/red-flag keyword lists, and returns only items worth
surfacing (matched a company, a macro keyword, or a red-flag term).
"""

import time
from fetch_nse_announcements import fetch_nse_announcements
from fetch_sebi import fetch_sebi_press_releases
from fetch_rss import fetch_rss_items
from matcher import classify
from config import GLOBAL_SOURCES
import events_store

_CACHE_TTL_SECONDS = 300
_cache = {"items": None, "at": 0}


def _classified_items(raw_items):
    rows = []
    for item in raw_items:
        result = classify(item["text"])

        # Silver/base-metal terms only count as a match from a global
        # source (see config.GLOBAL_SOURCES) -- the same keyword from a
        # local Indian source (NSE, SEBI, Economic Times, Business
        # Standard) is dropped rather than surfaced, since it's a local
        # event mentioning the metal, not a global price move.
        commodity_metal_terms = result["commodity_metal_terms"] if item["source"] in GLOBAL_SOURCES else []

        if not (
            result["symbols"] or result["macro_terms"] or result["positive_terms"]
            or result["red_flag_terms"] or commodity_metal_terms or result["daily_throttle_terms"]
        ):
            continue
        rows.append({
            "id": item["id"],
            "source": item["source"],
            "published": item["published"],
            "title": item["title"],
            "link": item["link"],
            "symbols": result["symbols"],
            "macro_terms": result["macro_terms"],
            "positive_terms": result["positive_terms"],
            "red_flag_terms": result["red_flag_terms"],
            "commodity_metal_terms": commodity_metal_terms,
            "daily_throttle_terms": result["daily_throttle_terms"],
            "is_red_flag": bool(result["red_flag_terms"]),
        })
    return rows


def get_matched_events(use_cache=True):
    """
    Fetches all three sources and returns matched/classified items, newest
    source-order first (NSE announcements, then SEBI, then RSS -- each
    source is already roughly newest-first from its own feed).
    """
    if use_cache and _cache["items"] is not None and (time.time() - _cache["at"]) < _CACHE_TTL_SECONDS:
        return _cache["items"]

    raw_items = []
    raw_items += fetch_nse_announcements()
    raw_items += fetch_sebi_press_releases()
    raw_items += fetch_rss_items()

    items = _classified_items(raw_items)
    events_store.save_events(items)
    _cache["items"] = items
    _cache["at"] = time.time()
    return items


if __name__ == "__main__":
    items = get_matched_events(use_cache=False)
    red_flags = [i for i in items if i["is_red_flag"]]
    print(f"{len(items)} matched items, {len(red_flags)} red-flagged.\n")
    for item in red_flags[:10]:
        print(f"[{item['source']}] {item['title']}")
        print(f"  red flags: {item['red_flag_terms']}  symbols: {item['symbols']}\n")
