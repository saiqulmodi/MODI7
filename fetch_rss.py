"""Fetches items from the configured financial news RSS feeds."""

import feedparser
from config import RSS_FEEDS


def fetch_rss_items():
    """Returns a list of dicts: {id, title, text, link, source, published}."""
    items = []
    for source_name, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"RSS fetch failed for {source_name}: {e}")
            continue

        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            link = entry.get("link", "")
            # id is source+title, not the link -- Google News RSS links embed
            # a per-fetch session/redirect token, so the SAME article gets a
            # DIFFERENT link (and therefore a different id, defeating dedup)
            # on every refetch. The title is stable across refetches; source
            # is prefixed so an identical headline from two different feeds
            # doesn't collide into a single dropped row.
            items.append({
                "id": f"{source_name}:{title}",
                "title": title,
                "text": f"{title} {summary}",
                "link": link,
                "source": source_name,
                "published": entry.get("published", ""),
            })
    return items


if __name__ == "__main__":
    for item in fetch_rss_items()[:5]:
        print(f"[{item['source']}] {item['title']}")
