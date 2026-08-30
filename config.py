"""
Shared configuration for MODI7's news/SEBI/announcement fetchers (staged
for Phase 2, not wired into the dashboard yet). Adapted from MODI3's
config.py -- same sources/keywords, but pointed at MODI7's own symbol
universe (universe.py) instead of importing across projects.
"""

import pandas as pd
from universe import MODI1_INTRADAY_SYMBOLS
from policy_exposure import ALL_POLICY_KEYWORDS

RSS_FEEDS = {
    "Economic Times Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Business Standard Markets": "https://www.business-standard.com/rss/markets-106.rss",
    "CNBC World Markets": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "CNBC Top News": "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    "Bloomberg Markets": "https://www.bloomberg.com/feeds/markets/news.rss",
    "Google News (global markets/Fed/geopolitical)": (
        "https://news.google.com/rss/search?q=global+markets+OR+federal+reserve"
        "+OR+geopolitical+when:1d&hl=en-US&gl=US&ceid=US:en"
    ),
    "Investing.com Commodities": "https://www.investing.com/rss/commodities.rss",
    "Google News (commodities)": (
        "https://news.google.com/rss/search?q=crude+oil+OR+gold+price+OR+silver+price"
        "+OR+commodities+when:1d&hl=en-US&gl=US&ceid=US:en"
    ),
}

NSE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities"
SEBI_PRESS_RELEASES_URL = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0"

# Macro/regulatory terms worth alerting on regardless of company mentioned.
MACRO_KEYWORDS = [
    "RBI", "repo rate", "SEBI circular", "SEBI order", "GDP", "inflation",
    "CPI", "WPI", "GST", "union budget", "monetary policy", "interest rate",
    "fiscal deficit", "credit policy", "FII", "DII", "current account deficit",
    "rating downgrade", "rating upgrade", "moody's", "s&p", "fitch",
    "federal reserve", "fed rate", "rate hike", "rate cut", "tariff",
    "sanctions", "trade war", "recession",
    "geopolitical", "china", "war", "ceasefire", "central bank",
    "silver price", "natural gas", "copper", "commodity prices",
] + [kw for kw in ALL_POLICY_KEYWORDS if kw not in {
    # Sector-specific policy levers from policy_exposure.py -- deduped
    # against terms already above (repo rate, sebi circular).
    "repo rate", "sebi circular",
}]

# Corporate-announcement categories worth alerting on for ANY company, not
# just the watchlist -- order wins and results updates are broad market
# interest, and NSE's corporate-announcements feed covers ~2000+ listed
# companies, most of which aren't on WATCHLIST_SYMBOLS at all.
ANNOUNCEMENT_CATEGORY_KEYWORDS = [
    "financial results", "award of order", "receipt of order",
    "bags order", "wins order", "l1 bidder", "lowest bidder",
    "order worth", "contract win", "order from",
    # Institutional/promoter buying and capital actions the market usually
    # reads as positive -- kept separate from RED_FLAG_KEYWORDS' selling
    # side of the same relationship (promoter selling, MF/FII exits).
    "mutual fund buys", "mutual fund increases stake", "mf buys",
    "mf increases stake", "fii buys stake", "dii buys stake",
    "promoter increases stake", "promoter buys shares", "promoter acquires shares",
    "buyback announcement", "buyback of shares", "bonus issue", "stock split",
    "acquires land", "land acquisition", "acquisition of property",
    "acquires stake in", "acquisition of business", "strategic investment in",
    # Analyst meet / concall -- surfaced as links, not full transcript
    # analysis (that would need PDF text extraction, a bigger separate lift).
    "investor presentation", "conference call transcript", "concall transcript",
    "analyst meet", "earnings call", "investor call",
    # Promoter/company policy changes -- neutral-to-watch, not inherently
    # positive or negative; kept in this bucket (rather than RED_FLAG_KEYWORDS)
    # so they don't get mislabeled as a confirmed problem in the dashboard.
    "change in dividend policy", "revised dividend policy",
    "capital allocation policy", "revised capital allocation policy",
    "related party transaction policy", "change in promoter",
    "reclassification of promoter", "promoter group reclassification",
    "scheme of arrangement", "demerger", "merger scheme", "slump sale",
    "hive-off", "strategic review", "change in management",
]

# Phase 2: terms that make an item worth flagging as a potential red flag --
# governance, legal, and financial-distress signals. Substring-matched
# case-insensitively against title+text, same as ANNOUNCEMENT_CATEGORY_KEYWORDS.
# This is a keyword net, not a verified classifier -- a match means "worth a
# human look," not "confirmed problem."
RED_FLAG_KEYWORDS = [
    "resignation of director", "director resigns", "auditor resign",
    "resignation of auditor", "forensic audit", "sebi bars", "sebi bans",
    "show cause notice",
    # Bare "insider trading" false-positives on the boilerplate "Trading
    # Window closure pursuant to SEBI (Prohibition of Insider Trading)
    # Regulations" filing every company makes routinely -- these more
    # specific phrases only match an actual reported violation/action.
    "insider trading violation", "insider trading case", "insider trading probe",
    "penalty for insider trading", "charged with insider trading",
    "cbi raid", "ed raid",
    "enforcement directorate", "income tax raid", "search and seizure",
    "insolvency", "ibc proceedings", "npa", "default on", "debt restructuring",
    "one time settlement", "winding up", "liquidation", "fraud",
    "misappropriation", "pledge of shares", "invocation of pledge",
    "promoter selling", "promoter sold", "promoter stake sale", "bulk deal",
    "block deal", "credit rating downgrade", "rating downgraded", "litigation",
    "court case", "lawsuit filed", "class action", "penalty imposed",
    "fine imposed", "regulatory action", "qualified opinion", "going concern",
    "rating watch negative", "outlook revised to negative",
    # Promoter-specific legal exposure -- distinct from the generic
    # litigation/court-case terms above, which can be about the company
    # itself (a customer/vendor dispute) rather than the promoters personally.
    "promoter arrested", "fir against promoter", "chargesheet against promoter",
    "cbi case against promoter", "ed summons promoter", "sebi debars promoter",
    "sebi bars promoter", "case against promoter",
    # Institutional exits -- the selling-side counterpart to the MF/FII
    # buying terms in ANNOUNCEMENT_CATEGORY_KEYWORDS.
    "mutual fund sells", "mutual fund reduces stake", "mf sells",
    "mf reduces stake", "fii sells stake", "dii sells stake",
    "institutional investor exits",
    # Governance/dilution red flags.
    "related party transaction", "voluntary delisting", "delisting of shares",
    # Divestment/disposal -- the selling-side counterpart to the property/
    # land/business acquisition terms in ANNOUNCEMENT_CATEGORY_KEYWORDS.
    "sells land", "disposal of property", "divests property", "divests stake in",
    "sale of business", "sells subsidiary",
]

WATCHLIST_SYMBOLS = set(MODI1_INTRADAY_SYMBOLS)


def load_symbol_to_name():
    """Maps ticker symbol -> full company name for NSE equities in the watchlist,
    so news mentioning a company by name (not just ticker) can still match."""
    scrips = pd.read_csv("nse_scrips.csv", low_memory=False)
    equities = scrips[(scrips["exchangename"] == "NSE") & (scrips["optiontype"] == "EQ")]
    mapping = {}
    for symbol in WATCHLIST_SYMBOLS:
        match = equities[equities["scripshortname"] == symbol]
        if not match.empty:
            mapping[symbol] = match.iloc[0]["scripfullname"]
    return mapping


SYMBOL_TO_NAME = load_symbol_to_name()
