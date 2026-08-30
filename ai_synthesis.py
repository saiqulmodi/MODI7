"""
Phase 3: AI synthesis layer. Runs a single LLM call over a company's
Phase 1 fundamentals + Phase 2 news/red-flags and returns a structured,
explicitly-labeled-as-inferred view: overall sentiment, plain-language
explanations of any red flags, and a running watch-list of what to track.

This is a single classification/summarization call, not an agent -- the
model only reasons over the structured data handed to it below (no web
access, no tools), and every prompt tells it to phrase interpretation as
inference, not fact, since promoter intent / litigation outcomes / fund
flows can't be verified from a keyword-matched news feed.

Tries Claude (Anthropic) first. If that call fails for any reason -- no
credential configured, billing/credit issue, rate limit, etc. -- it falls
back to Gemini (Google) automatically, so the AI View still works with
just one of the two providers configured. Requires ANTHROPIC_API_KEY
and/or GEMINI_API_KEY (or GOOGLE_API_KEY) in the environment; neither key
is embedded here. If both providers fail, get_ai_view() returns both
error messages.
"""

import time
from typing import List

import anthropic
from google import genai
from google.genai import types as genai_types
from pydantic import BaseModel

from fundamentals import get_fundamentals, get_analyst_view
import events_store

CLAUDE_MODEL = "claude-opus-5"
GEMINI_MODEL = "gemini-3.6-flash"
_CACHE_TTL_SECONDS = 3600
_cache = {}


class RedFlagExplanation(BaseModel):
    flag: str
    explanation: str


class AIView(BaseModel):
    sentiment: str
    summary: str
    red_flags_explained: List[RedFlagExplanation]
    watch_items: List[str]
    management_signals: List[str]


SYSTEM_PROMPT = (
    "You are a cautious equity research assistant reviewing one Indian listed "
    "company for a retail investor. You only know what's in the data block "
    "below -- no other knowledge of this company, no live market access, no "
    "browsing. Never state promoter intent, litigation outcomes, or mutual "
    "fund reasoning as settled fact -- phrase any interpretation as an "
    "inference ('this may suggest...', 'a plausible reading is...', 'worth "
    "asking management about...'). If the data doesn't support a claim, say "
    "the data doesn't show it rather than filling the gap from general "
    "knowledge or assumptions about the sector. sentiment must be exactly one "
    "of: Positive, Neutral, Negative, Mixed."
)


def _format_fundamentals(f):
    return (
        f"Company: {f['name']} ({f['symbol']}) -- {f['sector']} / {f['industry']}\n"
        f"Price: {f['price']}, Market Cap: {f['market_cap']}\n"
        f"P/E: {f['pe_trailing']}, P/B: {f['pb']}, EV/EBITDA: {f['ev_ebitda']}\n"
        f"ROE: {f['roe_pct']}%, ROCE: {f['roce_pct']}%, Net Margin: {f['net_profit_margin_pct']}%\n"
        f"Debt/Equity: {f['debt_to_equity']}\n"
        f"Revenue growth YoY: {f['revenue_growth_yoy_pct']}%, QoQ: {f['revenue_growth_qoq_pct']}%\n"
        f"Book value/share: {f['book_value_per_share']}, Price vs book gap: {f['valuation_gap_vs_book_pct']}%\n"
        f"Insider holding: {f['insider_holding_pct']}%, Institutional holding: {f['institution_holding_pct']}%"
    )


def _format_analyst(a):
    if a.get("error"):
        return f"No analyst coverage data available ({a['error']})."
    counts = a.get("recommendation_counts") or {}
    return (
        f"Target price -- mean: {a['target_mean']}, range: {a['target_low']}-{a['target_high']}, "
        f"current price: {a['current_price']}, upside to mean target: {a['upside_to_mean_pct']}%\n"
        f"Consensus: {a['recommendation_label']} "
        f"(Strong Buy {counts.get('strongBuy', 0)}, Buy {counts.get('buy', 0)}, "
        f"Hold {counts.get('hold', 0)}, Sell {counts.get('sell', 0)}, Strong Sell {counts.get('strongSell', 0)})"
    )


def _format_news(events):
    if not events:
        return "No news/filings captured for this company yet."
    lines = []
    for e in events[:20]:
        tags = ", ".join(e["red_flag_terms"] + e["macro_terms"] + e["positive_terms"])
        lines.append(f"- [{e['published']}] ({e['source']}) {e['title']}" + (f" [tags: {tags}]" if tags else ""))
    return "\n".join(lines)


def _call_claude(prompt):
    """Returns (AIView, None) on success, or (None, error_message) on failure."""
    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_format=AIView,
        )
        return response.parsed_output, None
    except anthropic.AuthenticationError:
        return None, "No Anthropic API credential configured (ANTHROPIC_API_KEY)."
    except anthropic.APIStatusError as e:
        return None, f"Claude request failed: {e.message}"
    except TypeError as e:
        if "authentication method" in str(e).lower():
            return None, "No Anthropic API credential configured (ANTHROPIC_API_KEY)."
        return None, f"Claude request failed: {e}"
    except Exception as e:
        return None, f"Claude request failed: {e}"


def _call_gemini(prompt):
    """Returns (AIView, None) on success, or (None, error_message) on failure."""
    try:
        client = genai.Client()  # reads GEMINI_API_KEY or GOOGLE_API_KEY
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=AIView,
            ),
        )
        if response.parsed is None:
            return None, "Gemini returned a response that didn't match the expected schema."
        return response.parsed, None
    except Exception as e:
        message = str(e)
        if "API key" in message or "API_KEY" in message:
            return None, "No Gemini API credential configured (GEMINI_API_KEY or GOOGLE_API_KEY)."
        return None, f"Gemini request failed: {message}"


def get_ai_view(symbol, use_cache=True):
    """
    Returns {sentiment, summary, red_flags_explained, watch_items, provider, error}.
    Tries Claude first, falls back to Gemini if Claude fails for any reason
    (missing credential, billing, rate limit, ...). error is set (and other
    fields absent) only if BOTH providers fail, or fundamentals couldn't be
    fetched.
    """
    cache_key = symbol.strip().upper()
    cached = _cache.get(cache_key)
    if use_cache and cached and (time.time() - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    fundamentals = get_fundamentals(symbol)
    if fundamentals.get("error"):
        return {"error": fundamentals["error"]}

    analyst = get_analyst_view(symbol)
    bare_symbol = fundamentals["symbol"].split(".")[0]
    news_events = events_store.query_events(symbol=bare_symbol, limit=20)

    prompt = (
        f"{_format_fundamentals(fundamentals)}\n\n"
        f"Analyst view:\n{_format_analyst(analyst)}\n\n"
        f"Recent news/filings (from NSE/SEBI/RSS, keyword-matched -- may be incomplete):\n"
        f"{_format_news(news_events)}\n\n"
        "Based only on the above: give an overall sentiment, a short summary "
        "(3-5 sentences) covering both the fundamentals and any news, an "
        "explanation for each red-flagged item (why it might matter, phrased "
        "as inference), and a short list of what to watch next for this stock. "
        "If there are no red flags in the data, return an empty list for "
        "red_flags_explained rather than inventing one. If the news includes a "
        "property/land/business acquisition or disposal, note in the summary "
        "how the market would plausibly read it (financed by debt vs. cash "
        "reserves, in-sector expansion vs. unrelated diversification) -- as "
        "inference, not fact. If the news includes a promoter/company policy "
        "change (dividend policy, capital allocation, related-party-transaction "
        "policy, promoter reclassification, scheme of arrangement/demerger), "
        "call it out explicitly in the summary or watch_items rather than "
        "letting it pass unmentioned as just another headline. Separately, for "
        "management_signals: look only at promoter/management/governance-"
        "related items in the news list above (director or auditor "
        "resignations, share pledges or pledge invocations, related-party "
        "transactions, promoter stake changes, policy changes, promoter "
        "reclassification) and give a short list of governance observations "
        "based strictly on those items -- not on any outside knowledge or "
        "general reputation of this company's management. If none of the "
        "news items above touch on management/governance, return an empty "
        "list for management_signals rather than commenting on management "
        "quality from general knowledge."
    )

    view, claude_error = _call_claude(prompt)
    provider = "Claude"
    if view is None:
        view, gemini_error = _call_gemini(prompt)
        provider = "Gemini"
        if view is None:
            return {"error": f"Claude failed ({claude_error}); Gemini fallback also failed ({gemini_error})."}

    result = {
        "sentiment": view.sentiment,
        "summary": view.summary,
        "red_flags_explained": [{"flag": r.flag, "explanation": r.explanation} for r in view.red_flags_explained],
        "watch_items": view.watch_items,
        "management_signals": view.management_signals,
        "provider": provider,
        "error": None,
    }
    _cache[cache_key] = (result, time.time())
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(get_ai_view("RELIANCE"), indent=2))
