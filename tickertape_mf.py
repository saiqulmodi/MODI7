"""
Real mutual fund-specific shareholding via tickertape.in. screener.in's
DII% lumps mutual funds together with insurance/banks/other domestic
institutions into one bucket; tickertape separately reports MF% (from its
quarterly shareholding-pattern breakdown) plus per-fund holding detail
(fund name, portfolio weight, 3-month change, rank change), all sourced
from the page's server-rendered __NEXT_DATA__ JSON payload -- no login
needed for this data.

Personal, non-commercial use only, deliberately more conservative than
screener_scraper.py: tickertape's Terms of Service explicitly restrict
copying/automated extraction of the Service (more assertive than
screener.in's silence on the topic), so this throttles harder (2s between
requests) and caches longer (12h), and -- like screener_scraper.py -- is
only ever called per-symbol on demand, never in a bulk scan.
"""

import json
import re
import time

import requests

_SEARCH_URL = "https://api.tickertape.in/search"
_STOCK_URL = "https://www.tickertape.in{slug}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Safari/537.36"}

_CACHE_TTL_SECONDS = 12 * 60 * 60
_MIN_REQUEST_INTERVAL_SECONDS = 2.0

_cache = {}
_slug_cache = {}
_last_request_at = 0.0


def _throttle():
    global _last_request_at
    elapsed = time.time() - _last_request_at
    if elapsed < _MIN_REQUEST_INTERVAL_SECONDS:
        time.sleep(_MIN_REQUEST_INTERVAL_SECONDS - elapsed)
    _last_request_at = time.time()


def _find_slug(bare_symbol):
    if bare_symbol in _slug_cache:
        return _slug_cache[bare_symbol]

    _throttle()
    resp = requests.get(_SEARCH_URL, params={"text": bare_symbol, "types": "stock"}, headers=_HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    for stock in data.get("data", {}).get("stocks", []):
        if stock.get("ticker") == bare_symbol:
            slug = stock["slug"]
            _slug_cache[bare_symbol] = slug
            return slug
    return None


def get_mf_holding(symbol):
    """
    Returns real mutual-fund-specific shareholding for a symbol:
    {mf_holding_pct, mf_holding_change_qoq_pct, funds: [{name, weight_pct,
    market_cap_pct, change_3m_pct, current_rank, prev_rank}, ...], error}.
    funds is sorted by market_cap_pct (tickertape's own "top holders" order).
    """
    bare_symbol = symbol.strip().upper().split(".")[0]

    cached = _cache.get(bare_symbol)
    if cached and (time.time() - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    try:
        slug = _find_slug(bare_symbol)
        if not slug:
            result = {"symbol": bare_symbol, "error": "Symbol not found on tickertape.in."}
            _cache[bare_symbol] = (result, time.time())
            return result

        _throttle()
        resp = requests.get(_STOCK_URL.format(slug=slug), headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        html = resp.text
    except requests.exceptions.RequestException as e:
        return {"symbol": bare_symbol, "error": f"Couldn't fetch tickertape.in data: {e}"}

    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not match:
        result = {"symbol": bare_symbol, "error": "Couldn't parse tickertape.in page (page structure may have changed)."}
        _cache[bare_symbol] = (result, time.time())
        return result

    try:
        page_data = json.loads(match.group(1))
        summary = page_data["props"]["pageProps"]["securitySummary"]
    except (ValueError, KeyError):
        result = {"symbol": bare_symbol, "error": "Couldn't parse tickertape.in data (page structure may have changed)."}
        _cache[bare_symbol] = (result, time.time())
        return result

    funds = []
    for f in summary.get("mfHoldings", []):
        meta = f.get("meta", {})
        funds.append({
            "name": meta.get("fullName") or meta.get("name"),
            "weight_pct": f.get("weight"),
            "market_cap_pct": round(f["marketCapPct"], 4) if f.get("marketCapPct") is not None else None,
            "change_3m_pct": round(f["change3m"], 4) if f.get("change3m") is not None else None,
            "current_rank": f.get("currentRank"),
            "prev_rank": f.get("prevRank"),
        })
    funds.sort(key=lambda f: f["market_cap_pct"] or 0, reverse=True)

    mf_pct, mf_change_qoq = None, None
    quarters = summary.get("holdings", {}).get("holdings", [])  # ascending by date
    if quarters:
        mf_pct = quarters[-1]["data"].get("mfPctT")
        if len(quarters) > 1 and mf_pct is not None:
            prev = quarters[-2]["data"].get("mfPctT")
            if prev is not None:
                mf_change_qoq = round(mf_pct - prev, 2)

    result = {
        "symbol": bare_symbol,
        "mf_holding_pct": round(mf_pct, 2) if mf_pct is not None else None,
        "mf_holding_change_qoq_pct": mf_change_qoq,
        "funds": funds,
        "error": None,
    }
    _cache[bare_symbol] = (result, time.time())
    return result


if __name__ == "__main__":
    data = get_mf_holding("RELIANCE")
    print("MF holding %:", data.get("mf_holding_pct"), "QoQ change:", data.get("mf_holding_change_qoq_pct"))
    for f in data.get("funds", [])[:5]:
        print(f)
