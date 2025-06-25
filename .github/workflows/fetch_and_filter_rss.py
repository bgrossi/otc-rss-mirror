import feedparser
import feedparser
import requests
import time
from datetime import datetime, timedelta
import pytz

FEED_URL = "https://www.otcmarkets.com/syndicate/rss.xml"
CUT_OFF = datetime.now(pytz.utc) - timedelta(days=4)

## robust fetch with 3 retries
for attempt in range(3):
    try:
        resp = requests.get(
            FEED_URL,
            timeout=10,
            headers={"User-Agent": "GitHub-Actions-RSS-Mirror/1.0"}
        )
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        break
    except Exception as e:
        print(f"[Attempt {attempt+1}/3] Fetch failed: {e}")
        time.sleep(5)
else:
    raise RuntimeError("Failed to retrieve RSS feed after 3 attempts")
lines = []

for entry in feed.entries:
    # Parse the published date into a datetime
    published = datetime(*entry.published_parsed[:6], tzinfo=pytz.utc)
    if published >= CUT_OFF:
        # Customize this line however you like:
        lines.append(f"{published.isoformat()}  {entry.title}  {entry.link}")

# Write to the text file
with open("rss.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
