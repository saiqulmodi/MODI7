"""
Live/intraday price candles via Angel One's SmartAPI -- reuses the working
login MODI1 already has (copied into this project as angel_login.py, which
is gitignored since it holds live credentials; see README for setup).

This is the "additional edge" data source for charts specifically -- a
broker API is built for quotes/candles, unlike yfinance/screener.in which
cover fundamentals. It is NOT used for fundamentals (Angel One doesn't
expose those) and is entirely optional: every function here degrades to a
clear error dict if angel_login.py/angel_scrips.json aren't present, so the
dashboard's yfinance-based daily chart (charts.py) always works regardless.
"""

import json
import os
import time

import requests

_SCRIPS_PATH = os.path.join(os.path.dirname(__file__), "angel_scrips.json")
_CANDLE_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"

_scrips_cache = None
_token_cache = {}


def is_configured():
    """True if both the login credentials file and the instrument master are present."""
    return os.path.exists(os.path.join(os.path.dirname(__file__), "angel_login.py")) and os.path.exists(_SCRIPS_PATH)


def _load_scrips():
    global _scrips_cache
    if _scrips_cache is None:
        with open(_SCRIPS_PATH, "r") as f:
            _scrips_cache = json.load(f)
    return _scrips_cache


def _find_symbol_token(symbol, suffix="-EQ"):
    bare = symbol.strip().upper().split(".")[0]
    if bare in _token_cache:
        return _token_cache[bare]
    target = bare + suffix
    for entry in _load_scrips():
        if entry.get("exch_seg") == "NSE" and entry.get("symbol") == target:
            _token_cache[bare] = entry.get("token")
            return _token_cache[bare]
    return None


def _auth_headers():
    import angel_login  # imported lazily so a missing/broken file only breaks Angel One features, not the whole app
    return {
        "Authorization": f"Bearer {angel_login.auth_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "1.2.3.4",
        "X-ClientPublicIP": "1.2.3.4",
        "X-MACAddress": "00:00:00:00:00:00",
        "X-PrivateKey": angel_login.API_KEY,
    }


def get_intraday_candles(symbol, interval="FIVE_MINUTE", from_date=None, to_date=None):
    """
    Returns a list of [timestamp, open, high, low, close, volume] rows for
    today's session (or the given from_date/to_date, format 'YYYY-MM-DD HH:MM'),
    or a dict with an 'error' key if Angel One isn't configured/reachable.
    """
    if not is_configured():
        return {"error": "Angel One not configured -- see README for setup."}

    token = _find_symbol_token(symbol)
    if not token:
        return {"error": f"No Angel One instrument token found for {symbol}."}

    today = time.strftime("%Y-%m-%d")
    from_date = from_date or f"{today} 09:15"
    to_date = to_date or f"{today} 15:30"

    try:
        headers = _auth_headers()
    except Exception as e:
        return {"error": f"Angel One login not available: {e}"}

    body = {
        "exchange": "NSE",
        "symboltoken": token,
        "interval": interval,
        "fromdate": from_date,
        "todate": to_date,
    }
    try:
        resp = requests.post(_CANDLE_URL, json=body, headers=headers, timeout=10)
        result = resp.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        return {"error": f"Couldn't fetch Angel One candles: {e}"}

    if not result.get("status"):
        message = result.get("message", "Angel One returned an error.")
        if "datetime can't be greater than current" in message:
            message = "Today's session hasn't started yet (or has just started) -- check back after market open (9:15 AM IST)."
        return {"error": message}

    return {"candles": result.get("data", []), "error": None}


if __name__ == "__main__":
    print("configured:", is_configured())
    print(get_intraday_candles("RELIANCE"))
