import feedparser
from datetime import datetime, timedelta
import pytz

# 1) URL of the RSS feed
FEED_URL = "https://www.otcmarkets.com/syndicate/rss.xml"
# 2) How far back to keep entries
CUT_OFF = datetime.now(pytz.utc) - timedelta(days=4)

feed = feedparser.parse(FEED_URL)
lines = []

for entry in feed.entries:
    # Parse the published date into a datetime
    published = datetime(*entry.published_parsed[:6], tzinfo=pytz.utc)
    if published >= CUT_OFF:
        # Customize this line however you like:
        lines.append(f"{published.isoformat()}  {entry.title}  {entry.link}")

# 3) Write to the text file
with open("rss.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
