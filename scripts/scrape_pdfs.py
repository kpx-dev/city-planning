"""Discover and download Garden Grove Development Projects Update List PDFs.

Strategy:
1. Try direct ggcity.org first.
2. Use the Internet Archive's CDX API to list every PDF on ggcity.org and pick those
   matching the DPU naming pattern (filename contains "dpu", "q1-final", etc.).
3. For each candidate, download from the live URL if reachable; otherwise fetch
   from the Wayback Machine using a recent snapshot in `id_/` mode (raw original bytes).
4. Confirm the PDF by searching its first/second page for "DEVELOPMENT PROJECTS UPDATE LIST".
5. Cache to data/raw/ keyed by URL slug. Write data/raw/manifest.json.

The first time this runs it ought to find ~30 historical DPUs going back to 2014.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from pathlib import Path
from urllib.parse import urlparse, quote

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
MANIFEST_PATH = RAW_DIR / "manifest.json"
URL_CACHE_PATH = RAW_DIR / "_url_cache.json"

UA = "city-planning-explorer/0.1 (https://github.com/kpx-dev/city-planning; kien@kienpham.com)"

CDX_BASE = "https://web.archive.org/cdx/search/cdx"
WAYBACK_BASE = "https://web.archive.org/web"

# Known PDF URLs that may not be in the CDX index (most recent quarter PDFs).
EXTRA_URLS = [
    "https://ggcity.org/sites/default/files/q1-2026-finalver2.pdf",
    "https://ggcity.org/sites/default/files/q1-2026-final.pdf",
    "https://ggcity.org/sites/default/files/q4-final.pdf",
    "https://ggcity.org/sites/default/files/q3-final-draft.pdf",
    "https://ggcity.org/sites/default/files/q3-final.pdf",
    "https://ggcity.org/sites/default/files/q2-final.pdf",
    "https://ggcity.org/sites/default/files/q1-final.pdf",
    "https://ggcity.org/sites/default/files/final-list.pdf",
    "https://ggcity.org/sites/default/files/dpu101314.pdf",
    "https://ggcity.org/sites/default/files/dpu2014-march2016.pdf",
    # NOTE: Weekly City Manager memos (wm*.pdf) embed the DPU as an attachment but
    # the parser's first-page validation can't see it (memo summary is on pages 1-2).
    # The standalone DPU PDFs above cover the same date ranges, so we don't crawl memos.
]

# Public CORS/HTTP relay used when ggcity.org is unreachable from this host
# (their edge silently drops some IP ranges). codetabs returns the original
# binary unmodified.
PROXY_TEMPLATE = "https://api.codetabs.com/v1/proxy?quest={url}"

DPU_PHRASE = re.compile(r"DEVELOPMENT\s+PROJECTS\s+UPDATE", re.IGNORECASE)
DPU_NAME_RE = re.compile(r"(dpu|q[1-4][\-_].*final|q[1-4]\d{2,4}|final-list)", re.IGNORECASE)

logger = logging.getLogger("scrape")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@dataclass
class Candidate:
    url: str
    wayback_ts: str | None = None  # latest Wayback timestamp, if available

    def wayback_url(self) -> str | None:
        if not self.wayback_ts:
            return None
        return f"{WAYBACK_BASE}/{self.wayback_ts}id_/{self.url}"


@dataclass
class DpuRecord:
    url: str  # Original (live) URL.
    fetched_via: str  # "live" or "wayback"
    local_path: str
    sha256: str
    size_bytes: int


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def load_cache() -> dict[str, str]:
    if URL_CACHE_PATH.exists():
        try:
            return json.loads(URL_CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_cache(cache: dict[str, str]) -> None:
    URL_CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True))


def cdx_lookup(s: requests.Session, prefix: str, limit: int = 10000) -> list[tuple[str, str]]:
    """Return list of (url, latest_timestamp) for PDFs under the prefix."""
    params = {
        "url": prefix,
        "matchType": "prefix",
        "output": "json",
        "filter": "mimetype:application/pdf",
        "limit": str(limit),
        "collapse": "urlkey",
    }
    try:
        r = s.get(CDX_BASE, params=params, timeout=30)
        r.raise_for_status()
        rows = r.json()
        out: list[tuple[str, str]] = []
        for row in rows[1:]:
            ts, url = row[1], row[2]
            out.append((url, ts))
        return out
    except Exception as e:
        logger.warning("CDX lookup failed for %s: %s", prefix, e)
        return []


def candidate_urls(s: requests.Session) -> list[Candidate]:
    """Discover candidate DPU URLs via Wayback CDX + extras."""
    pdfs: dict[str, str] = {}  # url -> latest_ts

    # Walk a few prefixes that are known to host DPU PDFs.
    prefixes = [
        "ggcity.org/sites/default/files/",
        "ggcity.org/internet/pdf/planning/",
        "ggcity.org/internet/pdf/commdev/",
        "ggcity.org/www/planning/",
        "ggcity.org/www/commdev/",
        "ggcity.org/city-files/",
        "ggcity.org/pdf/planning/",
        "ggcity.org/pdf/commdev/",
    ]
    for p in prefixes:
        rows = cdx_lookup(s, p)
        for url, ts in rows:
            # Only keep DPU-named files.
            name = url.rsplit("/", 1)[-1].lower()
            if not DPU_NAME_RE.search(name):
                continue
            # Latest timestamp wins (each row is already collapsed by urlkey).
            prev = pdfs.get(url)
            if prev is None or ts > prev:
                pdfs[url] = ts
        time.sleep(0.5)

    cands: list[Candidate] = []
    seen: set[str] = set()
    for url, ts in pdfs.items():
        if url in seen:
            continue
        seen.add(url)
        cands.append(Candidate(url=url, wayback_ts=ts))

    for url in EXTRA_URLS:
        if url not in seen:
            cands.append(Candidate(url=url, wayback_ts=None))
            seen.add(url)

    return cands


def url_slug(url: str) -> str:
    p = urlparse(url)
    path = p.path.lstrip("/").replace("/", "__")
    if not path.lower().endswith(".pdf"):
        path += ".pdf"
    return path


def try_fetch(s: requests.Session, url: str, dest: Path, timeout: int = 60) -> bool:
    try:
        with s.get(url, stream=True, timeout=timeout, allow_redirects=True) as r:
            if r.status_code != 200:
                return False
            ctype = r.headers.get("Content-Type", "").lower()
            if "html" in ctype:
                return False
            tmp = dest.with_suffix(".part")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
            tmp.rename(dest)
            return True
    except Exception as e:
        logger.warning("fetch error %s: %s", url, e)
        if dest.with_suffix(".part").exists():
            try:
                dest.with_suffix(".part").unlink()
            except OSError:
                pass
        return False


def fetch_with_fallback(s: requests.Session, c: Candidate, dest: Path) -> str | None:
    """Returns 'live', 'proxy', 'wayback', 'cached' or None."""
    if dest.exists() and dest.stat().st_size > 1024:
        # Already cached. Mark source as 'cached'.
        return "cached"
    # Try live first (short timeout because ggcity may be down).
    if try_fetch(s, c.url, dest, timeout=15):
        return "live"
    # Try the public CORS/HTTP relay (works even when ggcity blocks our egress).
    proxy_url = PROXY_TEMPLATE.format(url=c.url)
    if try_fetch(s, proxy_url, dest, timeout=120):
        return "proxy"
    # Try Wayback raw bytes.
    wb = c.wayback_url()
    if wb and try_fetch(s, wb, dest, timeout=60):
        return "wayback"
    return None


def check_dpu_phrase(pdf_path: Path) -> bool:
    """Confirm the PDF is a DPU.

    Older DPU PDFs lack the explicit "DEVELOPMENT PROJECTS UPDATE" title on page 1,
    but consistently include columns like CASE NO + APPLICANT + PROJECT DESCRIPTION.
    Accept either signal.
    """
    try:
        import fitz

        doc = fitz.open(pdf_path)
        try:
            for i in range(min(2, len(doc))):
                txt = doc[i].get_text("text") or ""
                if DPU_PHRASE.search(txt):
                    return True
                # Older format: tabular column headers + filename hint.
                if (
                    re.search(r"CASE\s*(NO|#)", txt, re.IGNORECASE)
                    and re.search(r"PROJECT\s+DESCRIPTION", txt, re.IGNORECASE)
                    and re.search(r"APPLICANT", txt, re.IGNORECASE)
                ):
                    name = pdf_path.name.lower()
                    if "dpu" in name or "final" in name or "update" in name:
                        return True
        finally:
            doc.close()
    except Exception as e:
        logger.warning("DPU phrase check failed for %s: %s", pdf_path, e)
    return False


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    s = session()

    logger.info("Discovering candidates via Wayback CDX...")
    cands = candidate_urls(s)
    logger.info("Found %d candidate DPU URLs", len(cands))

    records: list[DpuRecord] = []
    seen_sha: set[str] = set()
    skipped = 0

    def process(c: Candidate) -> DpuRecord | None:
        slug = url_slug(c.url)
        dest = RAW_DIR / slug
        via = fetch_with_fallback(s, c, dest)
        if via is None:
            return None
        if dest.stat().st_size < 1024:
            return None
        if not check_dpu_phrase(dest):
            return None
        h = sha256_of(dest)
        return DpuRecord(
            url=c.url,
            fetched_via=via,
            local_path=str(dest.relative_to(ROOT)),
            sha256=h,
            size_bytes=dest.stat().st_size,
        )

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(process, c): c for c in cands}
        for fut in as_completed(futures):
            c = futures[fut]
            try:
                rec = fut.result()
            except Exception as e:
                logger.warning("process error %s: %s", c.url, e)
                rec = None
            if rec is None:
                skipped += 1
                logger.info("SKIP %s", c.url)
                continue
            if rec.sha256 in seen_sha:
                logger.info("dup-sha skip %s", c.url)
                continue
            seen_sha.add(rec.sha256)
            records.append(rec)
            logger.info("OK %s (via %s, %d bytes)", c.url, rec.fetched_via, rec.size_bytes)

    logger.info("Confirmed %d DPU PDFs (skipped %d)", len(records), skipped)
    records.sort(key=lambda r: r.url)
    MANIFEST_PATH.write_text(json.dumps([asdict(r) for r in records], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
