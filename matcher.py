"""
Classifies a news/filing/circular item: which watchlist companies it
mentions (by ticker or full name), and which keyword categories it hits --
macro/regulatory, positive corporate-announcement, or red-flag.
"""

import re
from config import (
    WATCHLIST_SYMBOLS, SYMBOL_TO_NAME, MACRO_KEYWORDS,
    ANNOUNCEMENT_CATEGORY_KEYWORDS, RED_FLAG_KEYWORDS,
)


def _matched_keywords(text, keywords):
    # Word-boundary match, not plain substring -- a bare `in` check let short
    # keywords like "npa" false-positive inside unrelated words ("uNPAid").
    text_lower = text.lower()
    return [kw for kw in keywords if re.search(rf"\b{re.escape(kw.lower())}\b", text_lower)]


def find_matched_symbols(text):
    """Returns the watchlist symbols mentioned in text, by ticker or full company name."""
    matches = []
    for symbol in WATCHLIST_SYMBOLS:
        if re.search(rf"\b{re.escape(symbol)}\b", text):
            matches.append(symbol)
            continue
        company_name = SYMBOL_TO_NAME.get(symbol)
        if company_name and company_name.lower() in text.lower():
            matches.append(symbol)
    return matches


def classify(text):
    """
    Returns a dict: {symbols, macro_terms, positive_terms, red_flag_terms}.
    An item is "worth surfacing" if any of the four lists is non-empty.
    """
    return {
        "symbols": find_matched_symbols(text),
        "macro_terms": _matched_keywords(text, MACRO_KEYWORDS),
        "positive_terms": _matched_keywords(text, ANNOUNCEMENT_CATEGORY_KEYWORDS),
        "red_flag_terms": _matched_keywords(text, RED_FLAG_KEYWORDS),
    }


def find_matches(text):
    """Back-compat flat-list view: symbols + macro + positive + red-flag terms, all together."""
    result = classify(text)
    return result["symbols"] + result["macro_terms"] + result["positive_terms"] + result["red_flag_terms"]
