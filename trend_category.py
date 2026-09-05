"""
Fast technical trend-categorization pass for MODI7's MODI1 intraday universe.

Buckets each symbol two ways from the same single yfinance history() call per
symbol (so this is ~5x fewer Yahoo calls per symbol than the full fundamentals
scan, which hits Yahoo 5+ times per symbol):

  - CATEGORY_ORDER (Cat-1..Cat-7/Mixed): where the last close sits relative to
    its 20/50/100/200-day SIMPLE moving average (SMA -- every day in the
    window weighted equally).
  - EMA_CATEGORY_ORDER (Cat-1E..Cat-7E/MixedE): the same 7-tier logic, but
    against the 20/50/100/200-day EXPONENTIAL moving average (EMA -- recent
    days weighted more heavily, so it reacts faster to a new trend and lags
    less, at the cost of flipping back and forth more in choppy stretches).

Both categorizations are independent and meant to be compared side by side
(a symbol whose SMA and EMA tiers disagree is often an early trend-change
candidate -- EMA usually shifts first). Meant to run first so the slow
fundamentals scan can work through a smaller category subset per run instead
of the full ~530-symbol universe every time.
"""

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

_CACHE_TTL_SECONDS = 1800
_cache = {}

# Same markers as fundamentals.py -- Yahoo throttles bursty/concurrent access
# with 429s and, once throttled, often 401 "Invalid Crumb" until the session's
# crumb token refreshes. Retrying with backoff clears both in practice.
_RETRYABLE_MARKERS = ("Too Many Requests", "Rate limited", "Invalid Crumb", "429", "401")

CATEGORY_ORDER = ["Cat-1", "Cat-2", "Cat-3", "Cat-4", "Cat-5", "Cat-6", "Cat-7", "Mixed"]

CATEGORY_LABELS = {
    "Cat-1": "Strong uptrend -- above 200/100/50/20 SMA",
    "Cat-2": "Uptrend -- above 100/50/20 SMA, below 200 SMA",
    "Cat-3": "Early uptrend -- above 50/20 SMA, below 100 & 200 SMA",
    "Cat-4": "Nascent uptrend -- above 20 SMA only",
    "Cat-5": "Early downtrend -- below 20/50 SMA, above 100 & 200 SMA",
    "Cat-6": "Downtrend -- below 20/50/100 SMA, above 200 SMA",
    "Cat-7": "Strong downtrend -- below 200/100/50/20 SMA",
    "Mixed": "No clean SMA stack (choppy/mixed signal)",
}

EMA_CATEGORY_ORDER = ["Cat-1E", "Cat-2E", "Cat-3E", "Cat-4E", "Cat-5E", "Cat-6E", "Cat-7E", "MixedE"]

EMA_CATEGORY_LABELS = {
    "Cat-1E": "Strong uptrend -- above 200/100/50/20 EMA",
    "Cat-2E": "Uptrend -- above 100/50/20 EMA, below 200 EMA",
    "Cat-3E": "Early uptrend -- above 50/20 EMA, below 100 & 200 EMA",
    "Cat-4E": "Nascent uptrend -- above 20 EMA only",
    "Cat-5E": "Early downtrend -- below 20/50 EMA, above 100 & 200 EMA",
    "Cat-6E": "Downtrend -- below 20/50/100 EMA, above 200 EMA",
    "Cat-7E": "Strong downtrend -- below 200/100/50/20 EMA",
    "MixedE": "No clean EMA stack (choppy/mixed signal)",
}


def _is_retryable(exc):
    return any(marker in str(exc) for marker in _RETRYABLE_MARKERS)


def _with_retry(fn, retries=4, base_delay=3.0):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < retries and _is_retryable(e):
                time.sleep(base_delay * (2 ** attempt) + random.uniform(0, 1))
                continue
            raise
    raise last_exc


def _normalize_symbol(symbol):
    """NSE tickers need a '.NS' suffix for yfinance (BSE would be '.BO')."""
    symbol = symbol.strip().upper()
    if "." not in symbol:
        symbol = f"{symbol}.NS"
    return symbol


def _classify_tier(above20, above50, above100, above200):
    """Maps the 4 above/below-average flags onto one of 7 nested trend tiers
    (as a bare number string), or 'Mixed' when the flags don't form a clean
    nested stack (e.g. above the 200-day average but below the 50-day) --
    that happens in choppy/sideways names. Shared by the SMA and EMA
    categorizations, which differ only in which average fed the flags in."""
    if above20 and above50 and above100 and above200:
        return "1"
    if above20 and above50 and above100 and not above200:
        return "2"
    if above20 and above50 and not above100 and not above200:
        return "3"
    if above20 and not above50 and not above100 and not above200:
        return "4"
    if not above20 and not above50 and above100 and above200:
        return "5"
    if not above20 and not above50 and not above100 and above200:
        return "6"
    if not above20 and not above50 and not above100 and not above200:
        return "7"
    return "Mixed"


def _classify(above20, above50, above100, above200):
    tier = _classify_tier(above20, above50, above100, above200)
    return "Mixed" if tier == "Mixed" else f"Cat-{tier}"


def _classify_ema(above20, above50, above100, above200):
    tier = _classify_tier(above20, above50, above100, above200)
    return "MixedE" if tier == "Mixed" else f"Cat-{tier}E"


def get_trend_category(symbol):
    """
    Returns a dict with the symbol's trend category plus its last close and
    20/50/100/200-day SMAs, or a dict with an 'error' key if there isn't
    enough price history (needs 200+ trading days) or the fetch failed.
    """
    ticker_symbol = _normalize_symbol(symbol)

    cached = _cache.get(ticker_symbol)
    if cached and (time.time() - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    # Same jitter-before-call approach as fundamentals.py's get_bulk_fundamentals
    # -- spreads out bursts from the thread pool so Yahoo doesn't see several
    # requests land in the same instant.
    time.sleep(random.uniform(0.2, 0.5))

    try:
        df = _with_retry(lambda: yf.Ticker(ticker_symbol).history(period="1y", interval="1d"))
    except Exception as e:
        result = {"symbol": ticker_symbol, "error": f"Couldn't fetch price history: {e}"}
        _cache[ticker_symbol] = (result, time.time())
        return result

    if df is None or df.empty or len(df) < 200:
        result = {
            "symbol": ticker_symbol,
            "error": "Not enough price history (need 200+ trading days) for a 200-day SMA.",
        }
        _cache[ticker_symbol] = (result, time.time())
        return result

    close = df["Close"]
    sma20 = close.rolling(20).mean().iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma100 = close.rolling(100).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]
    # adjust=False matches the standard recursive EMA formula (each new value
    # is a weighted blend of today's close and yesterday's EMA) rather than
    # pandas' default reweighting of the whole history on every call.
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    ema100 = close.ewm(span=100, adjust=False).mean().iloc[-1]
    ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
    last_close = close.iloc[-1]

    category = _classify(
        last_close > sma20, last_close > sma50, last_close > sma100, last_close > sma200,
    )
    ema_category = _classify_ema(
        last_close > ema20, last_close > ema50, last_close > ema100, last_close > ema200,
    )

    result = {
        "symbol": ticker_symbol,
        "category": category,
        "ema_category": ema_category,
        "last_close": round(last_close, 2),
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
        "sma100": round(sma100, 2),
        "sma200": round(sma200, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "ema100": round(ema100, 2),
        "ema200": round(ema200, 2),
        "error": None,
    }
    _cache[ticker_symbol] = (result, time.time())
    return result


def get_bulk_trend_categories(symbols, max_workers=5, progress_callback=None):
    """
    Categorizes many symbols concurrently. max_workers is higher than
    fundamentals.get_bulk_fundamentals's (3) since this makes only 1 Yahoo
    call per symbol instead of 5+ -- still throttled (jitter + retry), just
    less conservatively since there's a lot less request volume to trip the
    rate limit with.

    progress_callback, if given, is called as (completed_count, total_count)
    after each symbol finishes, so a caller (e.g. a Streamlit progress bar)
    can reflect live progress.

    Returns results in the same order as `symbols` (not completion order).
    """
    total = len(symbols)
    results = [None] * total
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(get_trend_category, symbol): i for i, symbol in enumerate(symbols)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results[index] = future.result()
            except Exception as e:
                results[index] = {"symbol": symbols[index], "error": f"Couldn't fetch data: {e}"}
            completed += 1
            if progress_callback:
                progress_callback(completed, total)

    return results


if __name__ == "__main__":
    data = get_trend_category("RELIANCE")
    for k, v in data.items():
        print(f"{k:12} {v}")
