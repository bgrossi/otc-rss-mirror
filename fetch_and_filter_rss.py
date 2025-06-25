#!/usr/bin/env python3
"""
Pull https://www.otcmarkets.com/syndicate/rss.xml, keep only the last 4 days,
append new items to data/otc_rss_latest.txt, and discard anything older.
Run inside a GitHub Action every 15 min.
"""
from datetime import datetime, timedelta, timezone
import os, json, sys, hashlib, feedparser

FEED_URL = "https://www.otcmarkets.com/syndicate/rss.xml"
OUT_FILE = "data/otc_rss_latest.txt"
CUTOFF = datetime.now(timezone.utc) - timedelta(days=4)

# make sure the data/ folder exists
os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)

# ---------- helper ---------- #
def fingerprint(entry):
    """Stable hash so we don’t store duplicates."""
    return hashlib.sha256(
        (entry.get("id") or entry.get("link") or json.dumps(entry)).encode()
    ).hexdigest()

# ---------- load existing -------- #
existing = {}
if os.path.exists(OUT_FILE):
    with open(OUT_FILE, "r", encoding="utf-8") as f:
        for ln in f:
            try:
                rec = json.loads(ln)
                existing[fingerprint(rec)] = rec
            except json.JSONDecodeError:
                continue

# ---------- fetch feed ---------- #
feed = feedparser.parse(FEED_URL)
for e in feed.entries:
    published = (
        datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
        if e.get("published_parsed")
        else datetime.now(timezone.utc)
    )
    if published >= CUTOFF:
        fp = fingerprint(e)
        if fp not in existing:
            # convert to plain dict with only fields we care about
            existing[fp] = {
                "title": e.get("title"),
                "link": e.get("link"),
                "published": published.isoformat(),
                "summary": e.get("summary"),
            }

# ---------- prune >4 days old ---------- #
kept = {
    fp: rec
    for fp, rec in existing.items()
    if datetime.fromisoformat(rec["published"]) >= CUTOFF
}

# ---------- write back ---------- #
with open(OUT_FILE, "w", encoding="utf-8") as f:
    for rec in sorted(kept.values(), key=lambda r: r["published"], reverse=True):
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"Wrote {len(kept)} records to {OUT_FILE}")
