from datetime import datetime, timezone

import streamlit as st
import pandas as pd
from fundamentals import get_fundamentals, get_peer_comparison, get_bulk_fundamentals, get_analyst_view
from screener_scraper import get_screener_view
from tickertape_mf import get_mf_holding
from policy_exposure import get_policy_exposure
from charts import get_price_history, build_candlestick_figure
import angel_charts
from universe import MODI1_INTRADAY_SYMBOLS
from trend_category import (
    get_bulk_trend_categories, CATEGORY_ORDER, CATEGORY_LABELS,
    EMA_CATEGORY_ORDER, EMA_CATEGORY_LABELS,
)
from universe_scan_scheduled import load_snapshot
from events import get_matched_events
import events_store
from ai_synthesis import get_ai_view

st.set_page_config(page_title="MODI7 Fundamentals", layout="wide")

st.title("📊 MODI7 Company Fundamentals")
st.caption(
    "Phase 1: valuation ratios, financials, growth, peer comparison. Phase 2: news/filings red flags. "
    "Data via Yahoo Finance + NSE/SEBI/RSS -- cross-check anything decision-critical against the company's own filings."
)


def _normalize_symbol(symbol):
    """NSE tickers need a '.NS' suffix for yfinance (BSE would be '.BO') --
    matches fundamentals.py/charts.py/trend_category.py's identical helper.
    Needed here to key symbol_category_map (built from raw MODI1_INTRADAY_SYMBOLS)
    the same way the results table's "Symbol" column is (normalized), or the
    two never match and every stock falls into "Uncategorized"."""
    symbol = symbol.strip().upper()
    if "." not in symbol:
        symbol = f"{symbol}.NS"
    return symbol


def _fundamentals_row(r):
    if r.get("error"):
        return {"Symbol": r["symbol"], "Name": None, "Error": r["error"]}
    return {
        "Symbol": r["symbol"],
        "Name": r["name"],
        "Sector": r["sector"],
        "Price": r["price"],
        "P/E": r["pe_trailing"],
        "PEG": r.get("peg"),
        "P/B": r["pb"],
        "ROE %": r["roe_pct"],
        "Net Margin %": r["net_profit_margin_pct"],
        "D/E": r["debt_to_equity"],
        "Rev Growth YoY %": r["revenue_growth_yoy_pct"],
        "Rev Growth QoQ %": r["revenue_growth_qoq_pct"],
        "Market Cap (Cr)": round(r["market_cap"] / 1e7, 0) if r["market_cap"] else None,
        "Error": None,
    }


def _peer_comparison_row(r):
    """_fundamentals_row plus screener.in shareholding/pros-cons. Kept separate
    from _fundamentals_row since that's reused by the bulk universe scan
    (tab_universe), which must stay yfinance-only -- peer lists here are a
    handful of symbols, not several hundred, so the extra screener.in calls
    (cached, throttled) are fine."""
    row = _fundamentals_row(r)
    if row.get("Error"):
        return row
    screener = get_screener_view(r["symbol"])
    if not screener.get("error"):
        row["Promoter %"] = screener.get("promoter_holding_pct")
        row["FII %"] = screener.get("fii_holding_pct")
        row["DII %"] = screener.get("dii_holding_pct")
        row["Public %"] = screener.get("public_holding_pct")
        row["Screener Pros"] = "; ".join(screener.get("pros", [])) or None
        row["Screener Cons"] = "; ".join(screener.get("cons", [])) or None
    return row


def _format_ago(iso_ts):
    if not iso_ts:
        return "never"
    delta = datetime.now(timezone.utc) - datetime.fromisoformat(iso_ts)
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m ago"


def _trend_categories_from_snapshot(snapshot):
    """Reshapes the background job's snapshot into the same
    {symbol: get_trend_category()-shaped dict} form the live 'Categorize
    Universe' button produces, so both paths feed the same display code."""
    result = {}
    for symbol in MODI1_INTRADAY_SYMBOLS:
        entry = snapshot["symbols"].get(symbol, {})
        if "trend" in entry:
            d = dict(entry["trend"])
            d["error"] = None
            result[symbol] = d
        else:
            result[symbol] = {
                "symbol": symbol,
                "error": entry.get("trend_error", "Not yet categorized by the background job."),
            }
    return result


def _fundamentals_results_from_snapshot(snapshot):
    """Same reshaping as _trend_categories_from_snapshot, but for fundamentals
    -- produces a get_bulk_fundamentals()-shaped list."""
    results = []
    for symbol in MODI1_INTRADAY_SYMBOLS:
        entry = snapshot["symbols"].get(symbol, {})
        if "fundamentals" in entry:
            d = dict(entry["fundamentals"])
            d["error"] = None
            results.append(d)
        else:
            results.append({
                "symbol": symbol,
                "error": entry.get("fundamentals_error", "Not yet scanned by the background job."),
            })
    return results


def _load_snapshot_into_session(snapshot):
    st.session_state["trend_categories"] = _trend_categories_from_snapshot(snapshot)
    st.session_state["universe_results"] = _fundamentals_results_from_snapshot(snapshot)


tab_single, tab_universe, tab_events = st.tabs(
    ["Single Stock / Peers", "MODI1 Intraday Universe", "News & Red Flags"]
)

with tab_single:
    col1, col2 = st.columns([2, 3])
    with col1:
        symbol = st.text_input("Symbol (e.g. RELIANCE, TCS, INFY):", "RELIANCE").upper()
    with col2:
        peers_input = st.text_input("Peers to compare (comma-separated, optional):", "")

    if st.button("Load Fundamentals"):
        peer_symbols = [p.strip() for p in peers_input.split(",") if p.strip()]
        with st.spinner(f"Fetching fundamentals for {symbol}..."):
            st.session_state["fundamentals_results"] = get_peer_comparison(symbol, peer_symbols)

    # Stored in session_state, not gated on the button's own rerun -- later
    # buttons in this tab (e.g. "Generate AI View") trigger their own rerun,
    # and on that rerun st.button("Load Fundamentals") is False again, which
    # would otherwise make this whole section vanish.
    if "fundamentals_results" in st.session_state:
        results = st.session_state["fundamentals_results"]
        primary = results[0]
        if primary.get("error"):
            st.error(primary["error"])
            st.stop()

        st.success(f"{primary['name']} ({primary['symbol']}) -- {primary['sector']} / {primary['industry']}")

        st.subheader("Price chart")
        chart_period_labels = {"1mo": "1M", "3mo": "3M", "6mo": "6M", "1y": "1Y", "5y": "5Y"}
        chart_tab_labels = list(chart_period_labels.values())
        if angel_charts.is_configured():
            chart_tab_labels = ["Today (Live)"] + chart_tab_labels
        chart_tabs = st.tabs(chart_tab_labels)

        tab_offset = 0
        if angel_charts.is_configured():
            with chart_tabs[0]:
                intraday = angel_charts.get_intraday_candles(primary["symbol"])
                if intraday.get("error"):
                    st.caption(f"Live intraday unavailable: {intraday['error']}")
                elif not intraday["candles"]:
                    st.caption("No intraday candles yet for today's session.")
                else:
                    import pandas as _pd
                    intraday_df = _pd.DataFrame(
                        intraday["candles"], columns=["Date", "Open", "High", "Low", "Close", "Volume"]
                    ).set_index("Date")
                    st.plotly_chart(
                        build_candlestick_figure(intraday_df, f"{primary['symbol']} -- Today (5-min, Angel One)"),
                        use_container_width=True,
                    )
            tab_offset = 1

        for i, period in enumerate(chart_period_labels):
            with chart_tabs[i + tab_offset]:
                history = get_price_history(primary["symbol"], period=period)
                if isinstance(history, dict) and history.get("error"):
                    st.caption(history["error"])
                else:
                    st.plotly_chart(
                        build_candlestick_figure(history, f"{primary['symbol']} -- {chart_period_labels[period]}"),
                        use_container_width=True,
                    )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Price", f"₹{primary['price']:.2f}" if primary["price"] else "N/A")
        m2.metric("Market Cap", f"₹{primary['market_cap']/1e7:,.0f} Cr" if primary["market_cap"] else "N/A")
        m3.metric("P/E (trailing)", f"{primary['pe_trailing']:.2f}" if primary["pe_trailing"] else "N/A")
        m4.metric("P/B", f"{primary['pb']:.2f}" if primary["pb"] else "N/A")

        m5, m6, m7, m8 = st.columns(4)
        m5.metric("ROE", f"{primary['roe_pct']}%" if primary["roe_pct"] is not None else "N/A")
        m6.metric("Net Profit Margin", f"{primary['net_profit_margin_pct']}%" if primary["net_profit_margin_pct"] is not None else "N/A")
        m7.metric("Debt/Equity", f"{primary['debt_to_equity']:.2f}" if primary["debt_to_equity"] else "N/A")
        m8.metric("Revenue Growth YoY", f"{primary['revenue_growth_yoy_pct']}%" if primary["revenue_growth_yoy_pct"] is not None else "N/A")

        st.subheader("Valuation gap")
        vg1, vg2 = st.columns(2)
        vg1.metric("Book Value / Share", f"₹{primary['book_value_per_share']:.2f}" if primary["book_value_per_share"] else "N/A")
        vg2.metric(
            "Price vs Book Value gap",
            f"{primary['valuation_gap_vs_book_pct']}%" if primary["valuation_gap_vs_book_pct"] is not None else "N/A",
            help="Positive = market price trades above book value per share (premium to net assets).",
        )

        st.subheader("Shareholding pattern (screener.in)")
        screener = get_screener_view(primary["symbol"])
        if screener.get("error"):
            st.caption(f"{screener['error']} Falling back to Yahoo's approximate split below.")
            h1, h2 = st.columns(2)
            h1.metric("Insider holding (approx.)", f"{primary['insider_holding_pct']}%" if primary["insider_holding_pct"] is not None else "N/A")
            h2.metric("Institutional holding (approx.)", f"{primary['institution_holding_pct']}%" if primary["institution_holding_pct"] is not None else "N/A")
        else:
            st.caption("Latest quarter's promoter/FII/DII/public split, with change vs. the prior quarter.")

            def _holding_metric(col, label, key):
                pct = screener.get(f"{key}_holding_pct")
                delta = screener.get(f"{key}_holding_change_qoq_pct")
                col.metric(
                    label,
                    f"{pct}%" if pct is not None else "N/A",
                    delta=f"{delta:+}pp QoQ" if delta is not None else None,
                )

            h1, h2, h3, h4 = st.columns(4)
            _holding_metric(h1, "Promoter", "promoter")
            _holding_metric(h2, "FII", "fii")
            _holding_metric(h3, "DII", "dii")
            _holding_metric(h4, "Public", "public")

            if screener.get("promoter_holding_pct") is not None and screener.get("promoter_holding_change_qoq_pct", 0) < -0.5:
                st.warning(
                    f"🔴 Promoter holding dropped {abs(screener['promoter_holding_change_qoq_pct'])}pp "
                    "vs. last quarter -- check NSE shareholding filings/announcements for the reason."
                )

            if screener.get("pros") or screener.get("cons"):
                st.markdown("**screener.in's analysis** *(machine-generated by screener.in, not verified)*")
                pc1, pc2 = st.columns(2)
                with pc1:
                    st.markdown("Pros")
                    for p in screener.get("pros", []):
                        st.markdown(f"- {p}")
                with pc2:
                    st.markdown("Cons")
                    for c in screener.get("cons", []):
                        st.markdown(f"- {c}")

        st.subheader("Mutual fund holding (tickertape.in)")
        mf = get_mf_holding(primary["symbol"])
        if mf.get("error"):
            st.caption(mf["error"])
        else:
            st.caption(
                "Real mutual-fund-specific holding -- distinct from the DII% above, which lumps MFs "
                "together with insurance/banks/other domestic institutions."
            )
            mf1, mf2 = st.columns(2)
            mf1.metric("Total MF holding", f"{mf['mf_holding_pct']}%" if mf["mf_holding_pct"] is not None else "N/A")
            mf2.metric(
                "Change vs. last quarter",
                f"{mf['mf_holding_change_qoq_pct']:+}pp" if mf["mf_holding_change_qoq_pct"] is not None else "N/A",
            )
            if mf.get("funds"):
                st.markdown("**Top funds holding this stock**")
                fund_rows = [{
                    "Fund": f["name"],
                    "% of Company": f["market_cap_pct"],
                    "% of Fund's Portfolio": f["weight_pct"],
                    "3M Change (pp)": f["change_3m_pct"],
                    "Rank": f["current_rank"],
                    "Prev Rank": f["prev_rank"],
                } for f in mf["funds"]]
                st.dataframe(pd.DataFrame(fund_rows), hide_index=True, use_container_width=True)

        st.subheader("Analyst view")
        analyst = get_analyst_view(primary["symbol"])
        if analyst.get("error"):
            st.caption(analyst["error"])
        else:
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("Target Mean", f"₹{analyst['target_mean']:.2f}" if analyst["target_mean"] else "N/A")
            a2.metric(
                "Upside to Mean Target",
                f"{analyst['upside_to_mean_pct']}%" if analyst["upside_to_mean_pct"] is not None else "N/A",
            )
            a3.metric(
                "Target Range",
                f"₹{analyst['target_low']:.0f} - ₹{analyst['target_high']:.0f}"
                if analyst["target_low"] and analyst["target_high"] else "N/A",
            )
            a4.metric("Consensus", analyst["recommendation_label"] or "N/A")
            if analyst["recommendation_counts"]:
                c = analyst["recommendation_counts"]
                st.caption(
                    f"Analyst recommendations: {c['strongBuy']} Strong Buy, {c['buy']} Buy, "
                    f"{c['hold']} Hold, {c['sell']} Sell, {c['strongSell']} Strong Sell"
                )

        st.subheader("News & red flags for this company")
        bare_symbol = primary["symbol"].split(".")[0]
        company_events = events_store.query_events(symbol=bare_symbol, limit=50)
        if not company_events:
            st.caption(
                "No news/filings captured for this symbol yet -- visit the \"News & Red Flags\" tab "
                "and click \"Fetch Latest\" to start building history."
            )
        else:
            event_rows = [{
                "⚠": "🔴" if e["is_red_flag"] else "",
                "Source": e["source"],
                "Published": e["published"],
                "Title": e["title"],
                "Red Flags": ", ".join(e["red_flag_terms"]),
                "Other Matches": ", ".join(e["macro_terms"] + e["positive_terms"]),
                "Link": e["link"],
            } for e in company_events]
            st.dataframe(
                pd.DataFrame(event_rows), hide_index=True, use_container_width=True,
                column_config={"Link": st.column_config.LinkColumn(display_text="Open")},
            )

        st.subheader("Policy/regulatory exposure")
        exposure = get_policy_exposure(primary["sector"], primary["industry"])
        if not exposure:
            st.caption(f"No curated policy mapping for {primary['sector']} / {primary['industry']} yet.")
        else:
            st.caption(f"Policy levers relevant to {primary['industry']} companies (curated, not exhaustive):")
            for lever in exposure["levers"]:
                st.markdown(f"- {lever}")

            recent_macro_events = events_store.query_events(since_days=30, limit=1000)
            relevant_events = [
                e for e in recent_macro_events
                if any(term.lower() in exposure["keywords"] for term in e["macro_terms"])
            ]
            if relevant_events:
                st.markdown("**Recent policy news matching this company's exposure:**")
                policy_rows = [{
                    "Published": e["published"], "Title": e["title"],
                    "Matched Levers": ", ".join(t for t in e["macro_terms"] if t.lower() in exposure["keywords"]),
                    "Link": e["link"],
                } for e in relevant_events]
                st.dataframe(
                    pd.DataFrame(policy_rows), hide_index=True, use_container_width=True,
                    column_config={"Link": st.column_config.LinkColumn(display_text="Open")},
                )
            else:
                st.caption("No matching policy news captured in the last 30 days yet.")

        st.subheader("AI view (Phase 3)")
        st.caption(
            "One Claude call over the fundamentals, analyst view, and news above. Sentiment, red-flag "
            "explanations, and watch items are the model's inference from that data -- not verified fact. "
            "Uses a small amount of Anthropic API usage per click."
        )
        if st.button("Generate AI View"):
            with st.spinner("Asking Claude to synthesize..."):
                ai_result = get_ai_view(primary["symbol"])
            st.session_state["ai_view"] = {"symbol": primary["symbol"], **ai_result}

        cached_ai_view = st.session_state.get("ai_view")
        if cached_ai_view and cached_ai_view.get("symbol") == primary["symbol"]:
            if cached_ai_view.get("error"):
                st.error(cached_ai_view["error"])
            else:
                sentiment_emoji = {"Positive": "🟢", "Negative": "🔴", "Mixed": "🟡", "Neutral": "⚪"}
                st.markdown(f"**Sentiment: {sentiment_emoji.get(cached_ai_view['sentiment'], '')} {cached_ai_view['sentiment']}**")
                st.caption(f"Generated by {cached_ai_view.get('provider', 'unknown')}.")
                st.write(cached_ai_view["summary"])
                if cached_ai_view["red_flags_explained"]:
                    st.markdown("**Red flags explained (AI-inferred):**")
                    for item in cached_ai_view["red_flags_explained"]:
                        st.markdown(f"- **{item['flag']}**: {item['explanation']}")
                if cached_ai_view["watch_items"]:
                    st.markdown("**Watch items:**")
                    for w in cached_ai_view["watch_items"]:
                        st.markdown(f"- {w}")
                if cached_ai_view.get("management_signals"):
                    st.markdown("**Management/governance signals** *(inferred strictly from filings above, not general reputation)*")
                    for m in cached_ai_view["management_signals"]:
                        st.markdown(f"- {m}")

        if len(results) > 1:
            st.subheader("Peer comparison")
            st.caption(
                "Promoter/FII/DII/Public % and Pros/Cons are from screener.in (latest quarter's "
                "shareholding; pros/cons are screener's machine-generated summary, not verified fact)."
            )
            with st.spinner("Fetching screener.in shareholding for peers..."):
                peer_df = pd.DataFrame([_peer_comparison_row(r) for r in results])
            st.dataframe(
                peer_df.drop(columns=["Error"]),
                hide_index=True, use_container_width=True,
            )

        if primary.get("website"):
            st.markdown(f"[Company website]({primary['website']})")

with tab_universe:
    st.write(
        f"Scans MODI1's curated intraday trading universe -- **{len(MODI1_INTRADAY_SYMBOLS)} NSE symbols** "
        f"(from `intraday_watchlist.py`'s INTRADAY_SYMBOLS)."
    )
    st.caption(
        "A full fundamentals scan hits Yahoo Finance 5+ times per symbol (fetched concurrently, but "
        "deliberately throttled to avoid rate-limiting). Expect a full ~530-symbol scan to take 15-20+ "
        "minutes -- reliability over speed, since going faster is what triggers Yahoo blocking the whole "
        "scan. Some smaller/less-covered names will still come back with no data regardless."
    )

    snapshot = load_snapshot()
    if snapshot["symbols"]:
        st.info(
            f"**Background scan available** -- categories last refreshed "
            f"{_format_ago(snapshot.get('trend_updated_at'))}, fundamentals last refreshed "
            f"{_format_ago(snapshot.get('fundamentals_updated_at'))}. Runs automatically: "
            f"`MODI7_TrendScan` every 30 min, `MODI7_FundamentalsScan_*` 3x/day (pre-open, midday, close) "
            f"via Windows Task Scheduler -- no need to wait through a live scan below unless you want a "
            f"fresher read right now."
        )
        if st.button("Load Latest Background Scan"):
            _load_snapshot_into_session(snapshot)

        # First time this tab renders in a session, show the background scan
        # automatically rather than an empty tab -- the whole point of the
        # scheduled job is that results are ready to view within a click, not
        # a fresh 15-20 min wait.
        if "universe_results" not in st.session_state and "trend_categories" not in st.session_state:
            _load_snapshot_into_session(snapshot)

    st.subheader("Step 1 (optional) -- Categorize by trend")
    st.caption(
        "Buckets every symbol by where its price sits vs its 20/50/100/200-day SMA -- only 1 Yahoo call "
        "per symbol (vs 5+ for the fundamentals scan below), so this pass takes a few minutes for the "
        "full universe. Use this for an on-demand refresh; the background job above already does this "
        "automatically every 30 min."
    )

    if st.button("Categorize Universe"):
        progress_bar = st.progress(0)
        status_text = st.empty()

        def _on_cat_progress(completed, total):
            progress_bar.progress(completed / total)
            status_text.text(f"{completed}/{total} symbols categorized...")

        cat_results = get_bulk_trend_categories(MODI1_INTRADAY_SYMBOLS, progress_callback=_on_cat_progress)
        status_text.empty()
        progress_bar.empty()

        st.session_state["trend_categories"] = dict(zip(MODI1_INTRADAY_SYMBOLS, cat_results))
        st.session_state.pop("universe_results", None)

    category_pool = MODI1_INTRADAY_SYMBOLS
    symbol_category_map = {}
    if "trend_categories" in st.session_state:
        trend_categories = st.session_state["trend_categories"]
        categorized = {s: r for s, r in trend_categories.items() if not r.get("error")}
        uncategorized = {s: r for s, r in trend_categories.items() if r.get("error")}
        symbol_category_map = {_normalize_symbol(s): r["category"] for s, r in categorized.items()}

        # PEG comes from the fundamentals scan (Step 2 below), not this fast
        # trend pass, so it's only available once that scan has been run in
        # this session. When present, rank each category's stocks by PEG
        # (cheapest relative to growth first); symbols the fundamentals scan
        # hasn't covered (or without a PEG value) sort alphabetically after.
        peg_by_symbol = {}
        if "universe_results" in st.session_state:
            for r in st.session_state["universe_results"]:
                if not r.get("error") and r.get("peg") is not None:
                    peg_by_symbol[r["symbol"]] = r["peg"]

        def _peg_sort_key(item):
            symbol = item[0]
            peg = peg_by_symbol.get(_normalize_symbol(symbol))
            return (peg is None, peg if peg is not None else 0, symbol)

        counts = {cat: 0 for cat in CATEGORY_ORDER}
        for r in categorized.values():
            counts[r["category"]] += 1

        st.success(f"{len(categorized)} of {len(trend_categories)} symbols categorized.")
        counts_df = pd.DataFrame(
            [{"Category": c, "Description": CATEGORY_LABELS[c], "Symbols": counts[c]} for c in CATEGORY_ORDER]
        )
        st.dataframe(counts_df, hide_index=True, use_container_width=True)

        st.markdown("**Which stocks are in each category:**")
        for cat in CATEGORY_ORDER:
            cat_symbols = {s: r for s, r in categorized.items() if r["category"] == cat}
            if not cat_symbols:
                continue
            with st.expander(f"{cat} -- {CATEGORY_LABELS[cat]} ({len(cat_symbols)} symbols)"):
                cat_rows = [
                    {
                        "Symbol": s,
                        "PEG": peg_by_symbol.get(_normalize_symbol(s)),
                        "Last Close": r.get("last_close"),
                        "SMA20": r.get("sma20"),
                        "SMA50": r.get("sma50"),
                        "SMA100": r.get("sma100"),
                        "SMA200": r.get("sma200"),
                    }
                    for s, r in sorted(cat_symbols.items(), key=_peg_sort_key)
                ]
                st.dataframe(
                    pd.DataFrame(cat_rows), hide_index=True, use_container_width=True,
                    height=min(400, 60 + 35 * len(cat_rows)),
                )

        st.markdown("---")
        st.markdown(
            "**EMA-based categorization** -- same 7-tier logic (Cat-1E strongest uptrend .. Cat-7E "
            "strongest downtrend, MixedE choppy), but tested against the 20/50/100/200-day *exponential* "
            "moving average instead of the simple one. EMA weights recent days more heavily, so it "
            "reacts faster to a new trend -- a stock whose SMA and EMA tiers disagree is often an early "
            "trend-change candidate, since EMA usually shifts first."
        )
        ema_counts = {cat: 0 for cat in EMA_CATEGORY_ORDER}
        for r in categorized.values():
            ema_counts[r["ema_category"]] += 1

        ema_counts_df = pd.DataFrame(
            [{"Category": c, "Description": EMA_CATEGORY_LABELS[c], "Symbols": ema_counts[c]} for c in EMA_CATEGORY_ORDER]
        )
        st.dataframe(ema_counts_df, hide_index=True, use_container_width=True)

        st.markdown("**Which stocks are in each EMA category:**")
        for cat in EMA_CATEGORY_ORDER:
            cat_symbols = {s: r for s, r in categorized.items() if r["ema_category"] == cat}
            if not cat_symbols:
                continue
            with st.expander(f"{cat} -- {EMA_CATEGORY_LABELS[cat]} ({len(cat_symbols)} symbols)"):
                cat_rows = [
                    {
                        "Symbol": s,
                        "PEG": peg_by_symbol.get(_normalize_symbol(s)),
                        "Last Close": r.get("last_close"),
                        "EMA20": r.get("ema20"),
                        "EMA50": r.get("ema50"),
                        "EMA100": r.get("ema100"),
                        "EMA200": r.get("ema200"),
                    }
                    for s, r in sorted(cat_symbols.items(), key=_peg_sort_key)
                ]
                st.dataframe(
                    pd.DataFrame(cat_rows), hide_index=True, use_container_width=True,
                    height=min(400, 60 + 35 * len(cat_rows)),
                )

        # "Agree" means both schemes landed on the same tier number (Cat-3
        # and Cat-3E agree; Mixed and MixedE agree). A disagreement is where
        # EMA's faster reaction to price has already flipped tier while SMA
        # hasn't caught up yet (or vice versa).
        def _tier(cat):
            return cat[:-1] if cat.endswith("E") else cat

        agree_count = sum(1 for r in categorized.values() if _tier(r["category"]) == _tier(r["ema_category"]))
        st.caption(f"{agree_count} of {len(categorized)} symbols have matching SMA/EMA tiers.")

        with st.expander(f"{len(categorized) - agree_count} symbols where SMA and EMA tiers disagree"):
            disagree_rows = [
                {"Symbol": s, "SMA Category": r["category"], "EMA Category": r["ema_category"]}
                for s, r in sorted(categorized.items())
                if _tier(r["category"]) != _tier(r["ema_category"])
            ]
            st.dataframe(
                pd.DataFrame(disagree_rows), hide_index=True, use_container_width=True,
                height=min(400, 60 + 35 * len(disagree_rows)),
            )

        st.markdown("---")

        selected_categories = st.multiselect(
            "Categories to include in the fundamentals scan below:",
            options=CATEGORY_ORDER,
            default=CATEGORY_ORDER,
            format_func=lambda c: f"{c} -- {CATEGORY_LABELS[c]} ({counts[c]})",
        )
        category_pool = [s for s, r in categorized.items() if r["category"] in selected_categories]
        st.caption(
            f"{len(category_pool)} symbols match the selected categories "
            f"(out of {len(MODI1_INTRADAY_SYMBOLS)} total)."
        )

        if uncategorized:
            with st.expander(f"{len(uncategorized)} symbols couldn't be categorized"):
                st.dataframe(
                    pd.DataFrame([{"Symbol": s, "Error": r["error"]} for s, r in uncategorized.items()]),
                    hide_index=True, use_container_width=True,
                )
    else:
        st.caption("Not categorized yet -- fundamentals scan below will use the full universe.")

    st.subheader("Step 2 -- Scan fundamentals")

    scan_count = st.number_input(
        "Symbols to scan (reduce for a quicker test run):",
        min_value=min(10, len(category_pool)) if category_pool else 0,
        max_value=max(len(category_pool), 1),
        value=len(category_pool),
        step=10,
    )

    if st.button("Scan Universe"):
        symbols_to_scan = category_pool[:scan_count]
        progress_bar = st.progress(0)
        status_text = st.empty()

        def _on_progress(completed, total):
            progress_bar.progress(completed / total)
            status_text.text(f"{completed}/{total} symbols fetched...")

        results = get_bulk_fundamentals(symbols_to_scan, progress_callback=_on_progress)
        status_text.empty()
        progress_bar.empty()

        st.session_state["universe_results"] = results

    if "universe_results" in st.session_state:
        results = st.session_state["universe_results"]
        rows = [_fundamentals_row(r) for r in results]
        df = pd.DataFrame(rows)
        df["Category"] = df["Symbol"].map(symbol_category_map)

        ok_df = df[df["Error"].isna()].drop(columns=["Error"])
        failed_df = df[df["Error"].notna()]

        st.success(f"{len(ok_df)} of {len(df)} symbols returned data.")

        search = st.text_input("Filter by symbol or name contains:", "")
        display_df = ok_df
        if search.strip():
            mask = (
                display_df["Symbol"].str.contains(search, case=False, na=False)
                | display_df["Name"].str.contains(search, case=False, na=False)
            )
            display_df = display_df[mask]

        if symbol_category_map:
            # Grouped by trend category (Step 1's buckets) instead of one flat
            # table -- each category gets its own heading and sub-table.
            for cat in CATEGORY_ORDER + [None]:
                cat_df = display_df[display_df["Category"] == cat] if cat is not None else display_df[display_df["Category"].isna()]
                if cat_df.empty:
                    continue
                heading = f"{cat} -- {CATEGORY_LABELS[cat]}" if cat is not None else "Uncategorized"
                st.markdown(f"**{heading}** ({len(cat_df)} symbols)")
                st.dataframe(
                    cat_df.drop(columns=["Category"]).sort_values(
                        "Market Cap (Cr)", ascending=False, na_position="last"
                    ),
                    hide_index=True, use_container_width=True, height=min(400, 60 + 35 * len(cat_df)),
                )
        else:
            st.dataframe(
                display_df.drop(columns=["Category"]).sort_values(
                    "Market Cap (Cr)", ascending=False, na_position="last"
                ),
                hide_index=True, use_container_width=True, height=600,
            )

        if not failed_df.empty:
            with st.expander(f"{len(failed_df)} symbols with no data"):
                st.dataframe(failed_df[["Symbol", "Error"]], hide_index=True, use_container_width=True)

with tab_events:
    st.write(
        "Pulls NSE corporate announcements, SEBI circulars, and financial-news RSS feeds, and surfaces "
        "items that mention a MODI1 watchlist company, a macro/regulatory keyword, or a red-flag term "
        "(litigation, insolvency, auditor/director resignation, pledge, rating downgrade, etc.)."
    )
    st.caption(
        "Red-flag matching is a keyword net, not a verified classifier -- a match means \"worth a human look,\" "
        "not a confirmed problem. Every fetch is saved to a local history (modi7_events.db) so this view "
        "accumulates across days, not just the current session."
    )

    stored_count = events_store.count_events()
    st.caption(f"{stored_count} items in history so far.")

    if st.button("Fetch Latest News & Filings"):
        with st.spinner("Fetching NSE announcements, SEBI circulars, and RSS feeds..."):
            get_matched_events(use_cache=False)

    f1, f2, f3 = st.columns(3)
    with f1:
        symbol_filter = st.text_input("Filter by symbol (optional):", "").strip().upper()
    with f2:
        show_red_flags_only = st.checkbox("Red flags only", value=False)
    with f3:
        since_label = st.selectbox("Show items from:", ["Last 1 day", "Last 3 days", "Last 7 days", "All history"], index=2)
    since_days = {"Last 1 day": 1, "Last 3 days": 3, "Last 7 days": 7, "All history": None}[since_label]

    events = events_store.query_events(
        symbol=symbol_filter or None, red_flags_only=show_red_flags_only, since_days=since_days, limit=1000,
    )
    red_flags = [e for e in events if e["is_red_flag"]]
    st.success(f"{len(events)} matched items in this view, {len(red_flags)} red-flagged.")

    rows = []
    for e in events:
        rows.append({
            "⚠": "🔴" if e["is_red_flag"] else "",
            "Source": e["source"],
            "Published": e["published"],
            "Title": e["title"],
            "Symbols": ", ".join(e["symbols"]),
            "Red Flags": ", ".join(e["red_flag_terms"]),
            "Other Matches": ", ".join(e["macro_terms"] + e["positive_terms"]),
            "Link": e["link"],
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("⚠", ascending=False)
    st.dataframe(
        df, hide_index=True, use_container_width=True, height=600,
        column_config={"Link": st.column_config.LinkColumn(display_text="Open")},
    )
