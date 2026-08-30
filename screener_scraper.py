"""
Supplementary fundamentals from screener.in -- real promoter/FII/DII/public
shareholding (yfinance's insider/institution split doesn't map onto NSE's
disclosure categories) plus screener's own machine-generated pros/cons list,
which is the closest thing to a ready-made red-flag summary available.

Personal, non-commercial use only, scraped respectfully: robots.txt allows
/company/<symbol>/ pages (it blocks /user/*, sort/limit/page/search query
params, and quarterly source-XML, none of which this module touches),
requests are throttled to one at a time with a delay between them, and
results are cached for hours since shareholding/pros-cons don't move
intraday. This supplements fundamentals.py (yfinance) -- it is not a
replacement, and is not used in the bulk universe scan.
"""

import re
import time

import requests
from bs4 import BeautifulSoup

_CONSOLIDATED_URL = "https://www.screener.in/company/{symbol}/consolidated/"
_STANDALONE_URL = "https://www.screener.in/company/{symbol}/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Safari/537.36"}

_CACHE_TTL_SECONDS = 6 * 60 * 60
_MIN_REQUEST_INTERVAL_SECONDS = 1.5

_cache = {}
_last_request_at = 0.0

_SHAREHOLDING_LABEL_MAP = {
    "promoters": "promoter_holding_pct",
    "fiis": "fii_holding_pct",
    "diis": "dii_holding_pct",
    "public": "public_holding_pct",
    "government": "government_holding_pct",
}


def _throttle():
    global _last_request_at
    elapsed = time.time() - _last_request_at
    if elapsed < _MIN_REQUEST_INTERVAL_SECONDS:
        time.sleep(_MIN_REQUEST_INTERVAL_SECONDS - elapsed)
    _last_request_at = time.time()


def _fetch_page(symbol):
    """Consolidated report first; some companies (e.g. NBFCs, some banks) only publish standalone."""
    for url in (_CONSOLIDATED_URL.format(symbol=symbol), _STANDALONE_URL.format(symbol=symbol)):
        _throttle()
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code == 200:
            return resp.text
        if resp.status_code != 404:
            resp.raise_for_status()
    return None


def _parse_shareholding(soup):
    """Reads the latest quarter's row from the Quarterly Shareholding Pattern table."""
    result = {}
    table = soup.select_one("#quarterly-shp table.data-table")
    if table is None:
        return result

    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        raw_label = cells[0].get_text(" ", strip=True)
        label = re.sub(r"[^a-zA-Z ]", "", raw_label).strip().lower()
        key = _SHAREHOLDING_LABEL_MAP.get(label)
        if key is None:
            continue

        values = [c.get_text(strip=True).rstrip("%") for c in cells[1:] if c.get_text(strip=True)]
        if not values:
            continue
        try:
            latest = float(values[-1])
        except ValueError:
            continue
        result[key] = latest

        if len(values) > 1:
            try:
                result[key.replace("_holding_pct", "_holding_change_qoq_pct")] = round(latest - float(values[-2]), 2)
            except ValueError:
                pass

    return result


def _parse_pros_cons(soup):
    pros = [li.get_text(strip=True) for li in soup.select("div.pros ul li")]
    cons = [li.get_text(strip=True) for li in soup.select("div.cons ul li")]
    return pros, cons


def get_screener_view(symbol):
    """
    Returns real promoter/FII/DII/public shareholding (with QoQ change) and
    screener.in's machine-generated pros/cons for a symbol, or a dict with
    an 'error' key if the page couldn't be found/parsed. screener.in uses
    the bare NSE code (no .NS suffix).
    """
    bare_symbol = symbol.strip().upper().split(".")[0]

    cached = _cache.get(bare_symbol)
    if cached and (time.time() - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    try:
        html = _fetch_page(bare_symbol)
    except Exception as e:
        result = {"symbol": bare_symbol, "error": f"Couldn't fetch screener.in data: {e}"}
        _cache[bare_symbol] = (result, time.time())
        return result

    if html is None:
        result = {"symbol": bare_symbol, "error": "No screener.in page found for this symbol."}
        _cache[bare_symbol] = (result, time.time())
        return result

    soup = BeautifulSoup(html, "html.parser")
    shareholding = _parse_shareholding(soup)
    pros, cons = _parse_pros_cons(soup)

    result = {
        "symbol": bare_symbol,
        **shareholding,
        "pros": pros,
        "cons": cons,
        "error": None,
    }
    _cache[bare_symbol] = (result, time.time())
    return result


if __name__ == "__main__":
    for test_symbol in ("RELIANCE", "HDFCBANK", "M&M"):
        data = get_screener_view(test_symbol)
        print(f"--- {test_symbol} ---")
        for k, v in data.items():
            print(f"{k:35} {v}")
        print()
