import streamlit as st
import pandas as pd
from fundamentals import get_fundamentals, get_peer_comparison, get_bulk_fundamentals, get_analyst_view
from screener_scraper import get_screener_view
from universe import MODI1_INTRADAY_SYMBOLS
from events import get_matched_events
import events_store
from ai_synthesis import get_ai_view

st.set_page_config(page_title="MODI7 Fundamentals", layout="wide")

st.title("📊 MODI7 Company Fundamentals")
st.caption(
    "Phase 1: valuation ratios, financials, growth, peer comparison. Phase 2: news/filings red flags. "
    "Data via Yahoo Finance + NSE/SEBI/RSS -- cross-check anything decision-critical against the company's own filings."
)


def _fundamentals_row(r):
    if r.get("error"):
        return {"Symbol": r["symbol"], "Name": None, "Error": r["error"]}
    return {
        "Symbol": r["symbol"],
        "Name": r["name"],
        "Sector": r["sector"],
        "Price": r["price"],
        "P/E": r["pe_trailing"],
        "P/B": r["pb"],
        "ROE %": r["roe_pct"],
        "Net Margin %": r["net_profit_margin_pct"],
        "D/E": r["debt_to_equity"],
        "Rev Growth YoY %": r["revenue_growth_yoy_pct"],
        "Rev Growth QoQ %": r["revenue_growth_qoq_pct"],
        "Market Cap (Cr)": round(r["market_cap"] / 1e7, 0) if r["market_cap"] else None,
        "Error": None,
    }


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
                "Link": e["link"],
            } for e in company_events]
            st.dataframe(
                pd.DataFrame(event_rows), hide_index=True, use_container_width=True,
                column_config={"Link": st.column_config.LinkColumn(display_text="Open")},
            )

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

        if len(results) > 1:
            st.subheader("Peer comparison")
            st.dataframe(
                pd.DataFrame([_fundamentals_row(r) for r in results]).drop(columns=["Error"]),
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
        "A full scan hits Yahoo Finance once per symbol (fetched concurrently). "
        "Expect it to take a few minutes, and expect some smaller/less-covered names to come back with no data."
    )

    scan_count = st.number_input(
        "Symbols to scan (reduce for a quicker test run):",
        min_value=10, max_value=len(MODI1_INTRADAY_SYMBOLS), value=len(MODI1_INTRADAY_SYMBOLS), step=10,
    )

    if st.button("Scan Universe"):
        symbols_to_scan = MODI1_INTRADAY_SYMBOLS[:scan_count]
        progress_bar = st.progress(0)
        status_text = st.empty()

        def _on_progress(completed, total):
            progress_bar.progress(completed / total)
            status_text.text(f"{completed}/{total} symbols fetched...")

        results = get_bulk_fundamentals(symbols_to_scan, max_workers=8, progress_callback=_on_progress)
        status_text.empty()
        progress_bar.empty()

        st.session_state["universe_results"] = results

    if "universe_results" in st.session_state:
        results = st.session_state["universe_results"]
        rows = [_fundamentals_row(r) for r in results]
        df = pd.DataFrame(rows)

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

        st.dataframe(
            display_df.sort_values("Market Cap (Cr)", ascending=False, na_position="last"),
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
