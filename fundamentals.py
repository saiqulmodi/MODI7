"""
Core fundamentals engine for MODI7 -- Phase 1.

Pulls valuation ratios, financial statements, growth rates, and a rough
holdings breakdown for NSE-listed companies via yfinance (free, no broker
auth needed -- Angel One/Motilal only expose trading data, not fundamentals).
"""

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

# Fundamentals don't move intraday -- cache per-symbol results so repeated
# single lookups and universe scans within the same run don't re-hit Yahoo.
_CACHE_TTL_SECONDS = 900
_cache = {}

# Yahoo throttles bursty/concurrent access with 429 "Too Many Requests" and,
# once throttled, often also starts returning 401 "Invalid Crumb" until the
# session's crumb token is refreshed -- retrying with backoff clears both in
# practice. Don't retry other errors (e.g. 404 for a delisted/renamed ticker)
# since those won't resolve on their own.
_RETRYABLE_MARKERS = ("Too Many Requests", "Rate limited", "Invalid Crumb", "429", "401")


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


def _fetch_valid_info(ticker, retries=3, base_delay=2.0):
    """Under soft load Yahoo sometimes returns a 200 with an empty/stripped
    .info dict instead of raising -- confirmed by re-fetching several
    "no data found" symbols from a full-scan run in isolation and getting
    full data back immediately. _with_retry alone can't catch this since no
    exception is raised, so retry on "info has no price field" too, not
    just hard errors."""
    last_info = None
    for attempt in range(retries + 1):
        info = _with_retry(lambda: ticker.info)
        if info and (info.get("regularMarketPrice") is not None or info.get("currentPrice") is not None):
            return info
        last_info = info
        if attempt < retries:
            time.sleep(base_delay * (2 ** attempt) + random.uniform(0, 1))
    return last_info


def _normalize_symbol(symbol):
    """NSE tickers need a '.NS' suffix for yfinance (BSE would be '.BO')."""
    symbol = symbol.strip().upper()
    if "." not in symbol:
        symbol = f"{symbol}.NS"
    return symbol


def _safe_pct(value):
    """yfinance returns some ratios as fractions (0.06) and others as None -- normalize to percent or None."""
    return round(value * 100, 2) if value is not None else None


def _latest_two(df):
    """Given a yfinance financials/balance_sheet DataFrame (columns = report dates, newest first), return (latest, previous) columns or (None, None)."""
    if df is None or df.empty or df.shape[1] < 1:
        return None, None
    latest = df.iloc[:, 0]
    previous = df.iloc[:, 1] if df.shape[1] > 1 else None
    return latest, previous


def _row(series, *names):
    """Look up the first matching row label in a financials/balance_sheet column series."""
    if series is None:
        return None
    for name in names:
        if name in series.index:
            val = series[name]
            return None if val != val else val  # filter NaN
    return None


def get_fundamentals(symbol):
    """
    Returns a dict of fundamentals for a single symbol, or a dict with an
    'error' key if the ticker couldn't be resolved. Missing individual
    fields are returned as None rather than raising -- data availability
    varies a lot across smaller/less-covered NSE names.
    """
    ticker_symbol = _normalize_symbol(symbol)

    cached = _cache.get(ticker_symbol)
    if cached and (time.time() - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    # Jitter spreads out bursts when called from get_bulk_fundamentals's thread
    # pool -- several threads hitting Yahoo in the same instant is what tends
    # to trigger the rate limit in the first place. A full ~530-symbol scan
    # is worth taking slower over -- reliability over speed here.
    time.sleep(random.uniform(0.3, 0.8))

    try:
        ticker = yf.Ticker(ticker_symbol)
        info = _fetch_valid_info(ticker)
    except Exception as e:
        return {"symbol": ticker_symbol, "error": f"Couldn't fetch data: {e}"}

    if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
        result = {"symbol": ticker_symbol, "error": "No data found for this symbol -- check the ticker."}
        _cache[ticker_symbol] = (result, time.time())
        return result

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    book_value_per_share = info.get("bookValue")

    # ROE and net margin: use yfinance's info fields when present, else
    # compute from the raw statements (info['returnOnEquity'] is often None
    # for names Yahoo doesn't cover closely).
    roe = info.get("returnOnEquity")
    net_margin = info.get("profitMargins")

    # Small gaps between this symbol's own sequential calls -- a single
    # thread firing 5 Yahoo requests back-to-back with no spacing was still
    # bursty enough to trip the rate limit even with a modest thread pool.
    try:
        fin_latest, fin_prev = _latest_two(_with_retry(lambda: ticker.financials))
    except Exception:
        fin_latest, fin_prev = None, None
    time.sleep(random.uniform(0.3, 0.6))
    try:
        bs_latest, bs_prev = _latest_two(_with_retry(lambda: ticker.balance_sheet))
    except Exception:
        bs_latest, bs_prev = None, None
    time.sleep(random.uniform(0.3, 0.6))
    try:
        q_fin_latest, q_fin_prev = _latest_two(_with_retry(lambda: ticker.quarterly_financials))
    except Exception:
        q_fin_latest, q_fin_prev = None, None
    time.sleep(random.uniform(0.3, 0.6))

    net_income = _row(fin_latest, "Net Income", "Net Income Common Stockholders")
    revenue = _row(fin_latest, "Total Revenue")
    stockholders_equity = _row(bs_latest, "Stockholders Equity", "Common Stock Equity")
    ebit = _row(fin_latest, "EBIT")
    total_assets = _row(bs_latest, "Total Assets")
    current_liabilities = _row(bs_latest, "Current Liabilities")

    if roe is None and net_income and stockholders_equity:
        roe = net_income / stockholders_equity
    if net_margin is None and net_income and revenue:
        net_margin = net_income / revenue

    roce = None
    if ebit and total_assets and current_liabilities:
        capital_employed = total_assets - current_liabilities
        if capital_employed:
            roce = ebit / capital_employed

    # Revenue growth YoY from annual statements, QoQ from quarterly ones.
    revenue_prev = _row(fin_prev, "Total Revenue")
    revenue_growth_yoy = (revenue - revenue_prev) / revenue_prev if revenue and revenue_prev else None

    q_revenue = _row(q_fin_latest, "Total Revenue")
    q_revenue_prev = _row(q_fin_prev, "Total Revenue")
    revenue_growth_qoq = (
        (q_revenue - q_revenue_prev) / q_revenue_prev if q_revenue and q_revenue_prev else None
    )

    # Rough holdings breakdown. NOTE: Yahoo's "insiders"/"institutions"
    # categories don't map cleanly onto NSE's promoter/FII/DII disclosure
    # categories -- treat as an approximate signal, not a substitute for the
    # exchange shareholding-pattern filing.
    try:
        holders = _with_retry(lambda: ticker.major_holders)
        insider_pct = _safe_pct(holders.loc["insidersPercentHeld", "Value"]) if holders is not None and "insidersPercentHeld" in holders.index else None
        institution_pct = _safe_pct(holders.loc["institutionsPercentHeld", "Value"]) if holders is not None and "institutionsPercentHeld" in holders.index else None
    except Exception:
        insider_pct, institution_pct = None, None

    valuation_gap_pct = None
    if price and book_value_per_share:
        valuation_gap_pct = round((price - book_value_per_share) / book_value_per_share * 100, 2)

    result = {
        "symbol": ticker_symbol,
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "price": price,
        "market_cap": info.get("marketCap"),
        "pe_trailing": info.get("trailingPE"),
        "pe_forward": info.get("forwardPE"),
        "pb": info.get("priceToBook"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        # NOTE: unlike roe/profitMargins (true fractions), this yfinance
        # version already returns dividendYield on a percent scale (0.47
        # means 0.47%, not 47%) -- confirmed against Reliance's real ~0.3-0.5%
        # yield. Do not run this through _safe_pct.
        "dividend_yield_pct": info.get("dividendYield"),
        "roe_pct": _safe_pct(roe),
        "roce_pct": _safe_pct(roce),
        "net_profit_margin_pct": _safe_pct(net_margin),
        "debt_to_equity": info.get("debtToEquity"),
        "revenue_growth_yoy_pct": _safe_pct(revenue_growth_yoy),
        "revenue_growth_qoq_pct": _safe_pct(revenue_growth_qoq),
        "book_value_per_share": book_value_per_share,
        "valuation_gap_vs_book_pct": valuation_gap_pct,
        "insider_holding_pct": insider_pct,
        "institution_holding_pct": institution_pct,
        "website": info.get("website"),
        "error": None,
    }
    _cache[ticker_symbol] = (result, time.time())
    return result


_analyst_cache = {}


def get_analyst_view(symbol):
    """
    Returns broker/analyst target prices and recommendation consensus for a
    symbol, or a dict with an 'error' key if there's no analyst coverage --
    common for smaller-cap names outside the big broker houses' coverage.
    """
    ticker_symbol = _normalize_symbol(symbol)

    cached = _analyst_cache.get(ticker_symbol)
    if cached and (time.time() - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    time.sleep(random.uniform(0, 0.5))

    try:
        ticker = yf.Ticker(ticker_symbol)
        targets = _with_retry(lambda: ticker.analyst_price_targets)
    except Exception as e:
        result = {"symbol": ticker_symbol, "error": f"Couldn't fetch analyst data: {e}"}
        _analyst_cache[ticker_symbol] = (result, time.time())
        return result

    if not targets or targets.get("current") is None:
        result = {"symbol": ticker_symbol, "error": "No analyst coverage data found."}
        _analyst_cache[ticker_symbol] = (result, time.time())
        return result

    current_price = targets.get("current")
    target_mean = targets.get("mean")
    upside_to_mean_pct = None
    if current_price and target_mean:
        upside_to_mean_pct = round((target_mean - current_price) / current_price * 100, 2)

    recommendation_counts = None
    recommendation_label = None
    try:
        recs = _with_retry(lambda: ticker.recommendations)
        if recs is not None and not recs.empty:
            latest = recs.iloc[0]
            recommendation_counts = {
                "strongBuy": int(latest.get("strongBuy", 0)),
                "buy": int(latest.get("buy", 0)),
                "hold": int(latest.get("hold", 0)),
                "sell": int(latest.get("sell", 0)),
                "strongSell": int(latest.get("strongSell", 0)),
            }
            buy_side = recommendation_counts["strongBuy"] + recommendation_counts["buy"]
            sell_side = recommendation_counts["sell"] + recommendation_counts["strongSell"]
            hold_side = recommendation_counts["hold"]
            top = max(buy_side, sell_side, hold_side)
            if top == 0:
                recommendation_label = None
            elif top == buy_side:
                recommendation_label = "Buy"
            elif top == sell_side:
                recommendation_label = "Sell"
            else:
                recommendation_label = "Hold"
    except Exception:
        pass

    result = {
        "symbol": ticker_symbol,
        "current_price": current_price,
        "target_mean": target_mean,
        "target_high": targets.get("high"),
        "target_low": targets.get("low"),
        "target_median": targets.get("median"),
        "upside_to_mean_pct": upside_to_mean_pct,
        "recommendation_counts": recommendation_counts,
        "recommendation_label": recommendation_label,
        "error": None,
    }
    _analyst_cache[ticker_symbol] = (result, time.time())
    return result


def get_peer_comparison(symbol, peer_symbols):
    """Returns a list of fundamentals dicts: the primary symbol first, then each peer."""
    symbols = [symbol] + [p for p in peer_symbols if p.strip()]
    return [get_fundamentals(s) for s in symbols]


def get_bulk_fundamentals(symbols, max_workers=3, progress_callback=None):
    """
    Fetches fundamentals for many symbols concurrently (Yahoo's per-ticker
    .info call is the bottleneck -- sequential fetching of a several-hundred
    symbol universe would take minutes longer than necessary). max_workers is
    kept low (3) since each symbol makes 5+ separate Yahoo calls -- 8 (and
    even 4) still triggered Yahoo's rate limit (429s and, once throttled,
    401 "Invalid Crumb" errors, which then affected every remaining symbol
    for the rest of that run) across the full ~530-symbol universe scan.
    Reliability matters more than speed here -- a full scan taking several
    extra minutes is a fine trade for it actually completing.

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
            executor.submit(get_fundamentals, symbol): i for i, symbol in enumerate(symbols)
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
    data = get_fundamentals("RELIANCE")
    for k, v in data.items():
        print(f"{k:30} {v}")
