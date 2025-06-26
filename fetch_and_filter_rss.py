#!/usr/bin/env python3
"""
Mirror the OTC Markets syndicate RSS feed, retaining a rolling 4-day window.

• Source (only):  https://content.otcmarkets.com/syndicate/rss.xml
  – The host serves a bad TLS certificate, so we deliberately disable cert
    verification for this single request.

• Output: newline-delimited JSON → data/otc_rss_latest.txt
  (easy to `read_json(..., lines=True)` later).

• Designed to run inside a GitHub Action every 15 min, but works anywhere.

Dependencies:  requests, feedparser        (pip install feedparser requests)
Python ≥ 3.8
"""

from __future__ import annotations
import os, sys, json, time, hashlib, socket, http.client
from datetime import datetime, timedelta, timezone
from typing import Dict

import requests, urllib3, feedparser
from requests.exceptions import RequestException

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
FEED_URL        = "https://content.otcmarkets.com/syndicate/rss.xml"
OUT_FILE        = "data/otc_rss_latest.txt"
RETENTION_DAYS  = 4

# Retry policy
MAX_RETRIES     = 5            # 1 initial try + 4 retries
BACKOFF_FACTOR  = 2.0          # wait 2,4,8,16,32 seconds (≈1 min total)
TIMEOUT_SEC     = 30           # per HTTP request

USER_AGENT      = (
    "Mozilla/5.0 (compatible; otc-rss-fetcher/2.0; "
    "+https://github.com/<your-github-user>/otc_rss_mirror)"
)

# ──────────────────────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────────────────────
def fingerprint(entry: Dict) -> str:
    """
    Stable hash so an item isn’t duplicated even if the feed drops <guid>.
    """
    payload = entry.get("id") or entry.get("link") or json.dumps(entry, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fetch_feed() -> "feedparser.FeedParserDict":
    """
    Fetch the RSS feed with bounded retries and exponential back-off.
    Skips TLS verification because content.otcmarkets.com serves an invalid cert.
    Raises the final exception after MAX_RETRIES failures.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "close",
    }
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                FEED_URL,
                headers=headers,
                timeout=TIMEOUT_SEC,
                verify=False,          # ← deliberate (invalid cert)
                allow_redirects=True,
            )
            resp.raise_for_status()   # raises for HTTP 4xx/5xx
            return feedparser.parse(resp.content)
        except (RequestException, http.client.RemoteDisconnected, socket.timeout) as exc:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"All {MAX_RETRIES} fetch attempts failed") from exc
            wait = BACKOFF_FACTOR ** attempt
            print(
                f"[WARN] Fetch attempt {attempt} failed ({exc}); retrying in {wait}s…",
                file=sys.stderr,
            )
            time.sleep(wait)


# ──────────────────────────────────────────────────────────────────────────────
# Main script
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)

    # 1️⃣ Load existing snapshot (if any)
    existing: Dict[str, Dict] = {}
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                    existing[fingerprint(rec)] = rec
                except json.JSONDecodeError:
                    pass  # ignore malformed lines

    # 2️⃣ Fetch latest feed
    feed = fetch_feed()

    # 3️⃣ Merge new items
    for e in feed.entries:
        # Robust date handling
        if e.get("published_parsed"):
            published = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
        elif e.get("updated_parsed"):
            published = datetime(*e.updated_parsed[:6], tzinfo=timezone.utc)
        else:
            published = datetime.now(timezone.utc)

        if published >= cutoff:
            fp = fingerprint(e)
            if fp not in existing:
                existing[fp] = {
                    "title":     e.get("title"),
                    "link":      e.get("link"),
                    "published": published.isoformat(),
                    "summary":   e.get("summary"),
                }

    # 4️⃣ Prune anything older than RETENTION_DAYS
    kept = {
        fp: rec
        for fp, rec in existing.items()
        if datetime.fromisoformat(rec["published"]) >= cutoff
    }

    # 5️⃣ Write back (newest first for human-friendly diffs)
    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        for rec in sorted(kept.values(), key=lambda r: r["published"], reverse=True):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"[INFO] wrote {len(kept)} records to {OUT_FILE}")


if __name__ == "__main__":
    main()
