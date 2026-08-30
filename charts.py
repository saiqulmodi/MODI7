"""
Price charts for MODI7. yfinance's daily/weekly history is the reliable
default (no auth, works for the full universe); angel_charts.py supplements
it with live intraday candles via Angel One's SmartAPI when configured.
"""

import time

import plotly.graph_objects as go
import yfinance as yf

_CACHE_TTL_SECONDS = 900
_cache = {}


def _normalize_symbol(symbol):
    symbol = symbol.strip().upper()
    if "." not in symbol:
        symbol = f"{symbol}.NS"
    return symbol


def get_price_history(symbol, period="6mo", interval="1d"):
    """
    Returns a pandas DataFrame of OHLCV data (yfinance's history() shape,
    DatetimeIndex) for the given symbol/period/interval, or a dict with an
    'error' key if no data is available.
    """
    ticker_symbol = _normalize_symbol(symbol)
    cache_key = (ticker_symbol, period, interval)

    cached = _cache.get(cache_key)
    if cached and (time.time() - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    try:
        df = yf.Ticker(ticker_symbol).history(period=period, interval=interval)
    except Exception as e:
        return {"error": f"Couldn't fetch price history: {e}"}

    if df is None or df.empty:
        result = {"error": "No price history found for this symbol."}
        _cache[cache_key] = (result, time.time())
        return result

    _cache[cache_key] = (df, time.time())
    return df


def build_candlestick_figure(df, title):
    """Builds a Plotly candlestick figure (with a volume subplot) from an OHLCV DataFrame."""
    fig = go.Figure(data=[go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="Price", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
    )])
    fig.update_layout(
        title=title, xaxis_title=None, yaxis_title="Price (₹)",
        xaxis_rangeslider_visible=False, height=450, margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


if __name__ == "__main__":
    data = get_price_history("RELIANCE", period="1mo")
    print(data.tail())
