"""
Fetches NSE's live corporate announcements/filings feed (results, board
meeting outcomes, disclosures, etc.) -- the "companies' profit growth
submitted to SEBI/exchange" part of the brief.
"""

import requests
from datetime import date

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_nse_announcements():
    """Returns a list of dicts: {id, title, text, link, source, published}.

    Without an explicit from_date/to_date, NSE's endpoint only returns the
    ~20 most recent announcements platform-wide (a rolling window) --
    verified directly: on a normal trading day that's a tiny fraction of
    the day's actual filings, easily pushed off the list between 15-minute
    fetches during busy filing periods. Passing today's date explicitly
    returns the FULL day's announcements instead (191 items vs. 20 in the
    same check).
    """
    today = date.today().strftime("%d-%m-%Y")
    url = (
        "https://www.nseindia.com/api/corporate-announcements?index=equities"
        f"&from_date={today}&to_date={today}"
    )
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        data = response.json()
    except Exception as e:
        print(f"NSE announcements fetch failed: {e}")
        return []

    items = []
    for entry in data:
        symbol = entry.get("symbol", "")
        company = entry.get("sm_name", "")
        desc = entry.get("desc", "")
        text = entry.get("attchmntText", "")
        title = f"{company} ({symbol}): {desc}"
        items.append({
            "id": entry.get("seq_id") or f"{symbol}-{entry.get('an_dt')}",
            "title": title,
            "text": f"{title} {text}",
            "link": entry.get("attchmntFile", ""),
            "source": "NSE Corporate Announcements",
            "published": entry.get("an_dt", ""),
        })
    return items


if __name__ == "__main__":
    for item in fetch_nse_announcements()[:5]:
        print(f"[{item['published']}] {item['title']}")
