#!/usr/bin/env python3
"""
Pull the OTC Markets syndicate RSS feed, keep a 4-day rolling window, and
write JSON-lines to data/otc_rss_latest.txt.

Order of attack
---------------
1. https://www.otcmarkets.com/syndicate/rss.xml      (normal host, strict TLS)
2. https://content.otcmarkets.com/syndicate/rss.xml  (fallback, broken TLS)
3.  http://content.otcmarkets.com/syndicate/rss.xml  (plain HTTP last resort)

Requires:  requests, feedparser
Add both to your GitHub Actions "pip install" step.
"""

from __future__ import annotations
import json, os, sys, hashlib, socket, http.client
from datetime import datetime, timedelta, timezone
from typing import Dict

import feedparser, requests, urllib3
from urllib3.util import Retry
from requests.adapters import HTTPAdapter

###############################################################################
# Tunables
###############################################################################
OUT_FILE        = "data/otc_rss_latest.txt"
RETENTION_DAYS  = 4
USER_AGENT      = (
    "Mozilla/5.0 (compatible; otc-rss-fetcher/1.2; "
    "+https://github.com/<your-github-user>/otc_rss_mirror)"
)

PRIMARY_URL     = "https://www.otcmarkets.com/syndicate/rss.xml"
FALLBACK_URLS   = [
    "https://content.otcmarkets.com/syndicate/rss.xml",   # bad cert
    "http://content.otcmarkets.com/syndicate/rss.xml",    # no TLS
]

###############################################################################
# Helpers
###############################################################################
def fingerprint(entry: Dict) -> str:
    """Stable hash so the same item isn’t duplicated across runs."""
    return hashlib.sha256(
        (entry.get("id") or entry.get("link") or json.dumps(entry, sort_keys=True))
        .encode("utf-8")
    ).hexdigest()


def session_with_retries() -> requests.Session:
    """Return a requests.Session that retries connection + HTTP errors."""
    retry_cfg = Retry(
        total=6, connect=6, read=6,
        backoff_factor=2.0,                     # 0,2,4,8,16,32 ≈ 1 min worst-case
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    sess = requests.Session()
    sess.mount("http://",  HTTPAdapter(max_retries=retry_cfg))
    sess.mount("https://", HTTPAdapter(max_retries=retry_cfg))
    return sess


def fetch_feed() -> "feedparser.FeedParserDict":
    """
    Try the primary URL, then the fallback(s).  Skip TLS verification ONLY
    for the content.otcmarkets.com host because its cert is invalid.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "close",
    }
    sess = session_with_retries()

    urls = [PRIMARY_URL] + FALLBACK_URLS
    last_exc: Exception | None = None

    for url in urls:
        verify_tls = not url.startswith("https://content.otcmarkets.com")
        try:
            if not verify_tls:
                # Silence "InsecureRequestWarning: Unverified HTTPS request"
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            resp = sess.get(url, headers=headers, timeout=30, verify=verify_tls)
            resp.raise_for_status()
            return feedparser.parse(resp.content)
        except (requests.exceptions.RequestException,
                http.client.RemoteDisconnected,
                socket.timeout) as exc:
            last_exc = exc
            print(f"[WARN] fetch via {url} failed: {exc}", file=sys.stderr)

    raise RuntimeError(f"All fetch attempts failed; last error: {last_exc!r}")

###############################################################################
# Main
###############################################################################
def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)

    # 1️⃣ load existing snapshot
    existing: Dict[str, Dict] = {}
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                    existing[fingerprint(rec)] = rec
                except json.JSONDecodeError:
                    pass

    # 2️⃣ fetch + merge
    feed = fetch_feed()
    for e in feed.entries:
        published = (
            datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
            if e.get("published_parsed")
            else datetime.now(timezone.utc)
        )
        if published >= cutoff:
            fp = fingerprint(e)
            if fp not in existing:
                existing[fp] = {
                    "title":     e.get("title"),
                    "link":      e.get("link"),
                    "published": published.isoformat(),
                    "summary":   e.get("summary"),
                }

    # 3️⃣ prune > RETENTION_DAYS old
    kept = {
        fp: rec
        for fp, rec in existing.items()
        if datetime.fromisoformat(rec["published"]) >= cutoff
    }

    # 4️⃣ write back (newest first for nice diffs)
    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        for rec in sorted(kept.values(), key=lambda r: r["published"], reverse=True):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"[INFO] wrote {len(kept)} records to {OUT_FILE}")

if __name__ == "__main__":
    main()
