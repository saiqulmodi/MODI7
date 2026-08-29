"""
Fetches SEBI's own circulars/regulatory listing page -- the "SEBI creating
a new alert/order as reported" part of the brief.
"""

import requests
from bs4 import BeautifulSoup

SEBI_URL = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_sebi_press_releases():
    """Returns a list of dicts: {id, title, text, link, source, published}."""
    try:
        response = requests.get(SEBI_URL, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        print(f"SEBI fetch failed: {e}")
        return []

    items = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        date_text = cells[0].get_text(strip=True)
        link_tag = cells[1].find("a")
        if not link_tag:
            continue
        title = link_tag.get_text(strip=True)
        link = link_tag.get("href", "")
        if not title or not link:
            continue
        items.append({
            "id": link,
            "title": title,
            "text": title,
            "link": link,
            "source": "SEBI Circulars",
            "published": date_text,
        })
    return items


if __name__ == "__main__":
    for item in fetch_sebi_press_releases()[:5]:
        print(f"[{item['published']}] {item['title']}")
