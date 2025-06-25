import feedparser
import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
from datetime import datetime, timedelta
import pytz

FEED_URL = "https://www.otcmarkets.com/syndicate/rss.xml"
CUT_OFF = datetime.now(pytz.utc) - timedelta(days=4)

## set up a session with retry on connect/read failures
session = requests.Session()
retry_strategy = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)

try:
    # timeout=(connect, read)
    resp = session.get(
        FEED_URL,
        timeout=(5, 30),
        headers={"User-Agent": "GitHub-Actions-RSS-Mirror/1.0"}
    )
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
except requests.exceptions.ReadTimeout as e:
    raise RuntimeError(f"Read timed out after 30s: {e}")
except Exception as e:
    raise RuntimeError(f"Failed to fetch RSS feed: {e}")

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
