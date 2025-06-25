#!/usr/bin/env python3
"""
Fetch https://www.otcmarkets.com/syndicate/rss.xml (or its HTTP fallback),
retry politely on network hic-cups, keep only the last 4 days of items, and
store them as newline-delimited JSON in data/otc_rss_latest.txt.

Designed for a GitHub Action that runs every 15 minutes.
---------------------------------------------------------------------------
Dependencies  : requests, feedparser  (add both to pip install step)
Python target : 3.8+
Author        : <your-github-user> (otc_rss_mirror project)
"""

from __future__ import annotations

import json, os, sys, hashlib, socket, http.client, time
from datetime import datetime, timedelta, timezone
from typing import Dict

import feedparser
import requests
from urllib3.util import Retry
from requests.adapters import HTTPAdapter

# --------------------------------------------------------------------------
# Basic parameters — tweak to taste
# --------------------------------------------------------------------------

FEED_URLS = [
    "https://www.otcmarkets.com/syndicate/rss.xml",
    "http://www.otcmarkets.com/syndicate/rss.xml",   # fallback if HTTPS misbehaves
]
OUT_FILE = "data/otc_rss_latest.txt"
RETENTION_DAYS = 4

USER_AGENT = (
    "Mozilla/5.0 (compatible; otc-rss-fetcher/1.1; "
    "+https://github.com/<your-github-user>/otc_rss_mirror)"
)

# --------------------------------------------------------------------------
# Robust fetch with retries and exponential back-off
# --------------------------------------------------------------------------

def fetch_feed() -> "feedparser.FeedParserDict":
    """
    Return a parsed feed (feedparser dict) after retrying connection errors,
    HTTPS failures, 429/5xx responses, etc. Falls back to HTTP.
    Raises the last exception if *all* attempts fail.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "close",
    }

    retry_cfg = Retry(
        total=6,               # 1 try + 5 retries
        connect=6,
        read=6,
        backoff_factor=2.0,    # delays: 0, 2, 4, 8, 16, 32  (≈1 min total)
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False, # we'll raise manually after retries
    )

    sess = requests.Session()
    sess.mount("http://",  HTTPAdapter(max_retries=retry_cfg))
    sess.mount("https://", HTTPAdapter(max_retries=retry_cfg))

    last_exc: Exception | None = None
    for url in FEED_URLS:                # try HTTPS first, then HTTP fallback
        try:
            resp = sess.get(url, headers=headers, timeout=30)
            resp.raise_for_status()      # may raise after retries
            return feedparser.parse(resp.content)
        except (requests.exceptions.RequestException,
                http.client.RemoteDisconnected,
                socket.timeout) as exc:
            last_exc = exc
            print(f"[WARN] Fetch error via {url}: {exc}", file=sys.stderr)

    raise last_exc  # all attempts failed

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def fingerprint(entry: Dict) -> str:
    """
    Produce a stable content-based hash so we can de-duplicate items even if
    the feed sometimes omits the <guid>.
    """
    return hashlib.sha256(
        (entry.get("id") or entry.get("link") or json.dumps(entry, sort_keys=True))
        .encode("utf-8")
    ).hexdigest()

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)

    # Ensure data/ folder exists
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)

    # Load existing records (if any)
    existing: Dict[str, Dict] = {}
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    existing[fingerprint(rec)] = rec
                except json.JSONDecodeError:
                    continue  # skip malformed lines

    # Fetch RSS with retries
    feed = fetch_feed()

    # Merge new items
    for e in feed.entries:
        # Robust published date handling
        if e.get("published_parsed"):
            published_dt = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
        elif e.get("updated_parsed"):
            published_dt = datetime(*e.updated_parsed[:6], tzinfo=timezone.utc)
        else:
            published_dt = datetime.now(timezone.utc)

        if published_dt >= cutoff:
            fp = fingerprint(e)
            if fp not in existing:
                existing[fp] = {
                    "title": e.get("title"),
                    "link": e.get("link"),
                    "published": published_dt.isoformat(),
                    "summary": e.get("summary"),
                }

    # Prune anything older than retention window
    kept = {
        fp: rec
        for fp, rec in existing.items()
        if datetime.fromisoformat(rec["published"]) >= cutoff
    }

    # Write back (newest first for human-friendly diff)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for rec in sorted(kept.values(), key=lambda r: r["published"], reverse=True):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"[INFO] Wrote {len(kept)} records to {OUT_FILE}")

if __name__ == "__main__":
    main()
