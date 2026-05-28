"""Discover and download Santa Ana, CA development project sources.

Two sources:
  A. Major Projects HTML table at
     https://www.santa-ana.org/major-planning-projects-and-monthly-development-project-reports/
  B. Monthly Accepted Development Projects PDFs, indexed at
     https://www.santa-ana.org/monthly-accepted-development-project-applications/
     Each linked page is a wrapper containing one storage.googleapis.com PDF URL.

Output:
  data/raw/santaana/major-projects.html
  data/raw/santaana/<month>-<year>.pdf  (e.g. january-2026.pdf)
  data/raw/santaana/manifest.json       (one record per source)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "santaana"
MANIFEST_PATH = RAW_DIR / "manifest.json"

UA = "city-planning-explorer/0.1 (https://github.com/kpx-dev/city-planning; kien@kienpham.com)"

MAJOR_URL = "https://www.santa-ana.org/major-planning-projects-and-monthly-development-project-reports/"
MONTHLY_INDEX_URL = "https://www.santa-ana.org/monthly-accepted-development-project-applications/"

POLITE_DELAY = 1.5

logger = logging.getLogger("santaana_scrape")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@dataclass
class Source:
    kind: str  # "major" or "monthly"
    url: str  # original wrapper page URL or major page URL
    pdf_url: str | None
    local_path: str
    sha256: str | None
    size_bytes: int
    title: str
    period_label: str | None  # e.g. "january-2026"


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en"})
    return s


def fetch_text(s: requests.Session, url: str, timeout: int = 30) -> str | None:
    for attempt in range(2):
        try:
            r = s.get(url, timeout=timeout, allow_redirects=True)
            if r.status_code == 200:
                return r.text
            logger.warning("non-200 %s -> %d", url, r.status_code)
            return None
        except Exception as e:
            logger.warning("fetch_text error %s (try %d): %s", url, attempt + 1, e)
            time.sleep(2)
    return None


def fetch_bytes(s: requests.Session, url: str, dest: Path, timeout: int = 60) -> bool:
    if dest.exists() and dest.stat().st_size > 1024:
        return True
    for attempt in range(2):
        try:
            with s.get(url, stream=True, timeout=timeout) as r:
                if r.status_code != 200:
                    logger.warning("non-200 %s -> %d", url, r.status_code)
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
            logger.warning("fetch_bytes error %s (try %d): %s", url, attempt + 1, e)
            time.sleep(2)
    return False


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


WRAPPER_RE = re.compile(
    r"^/documents/monthly-accepted-development-projects-(?:of|for)-([a-z]+-\d{4})/?$"
)
PDF_HOST = "storage.googleapis.com"


def discover_monthly_wrappers(s: requests.Session) -> list[tuple[str, str]]:
    """Return list of (wrapper_url, period_label like 'january-2026')."""
    html = fetch_text(s, MONTHLY_INDEX_URL)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        path = urlparse(urljoin(MONTHLY_INDEX_URL, href)).path
        m = WRAPPER_RE.match(path)
        if not m:
            continue
        full = urljoin(MONTHLY_INDEX_URL, href)
        if full in seen:
            continue
        seen.add(full)
        out.append((full, m.group(1)))
    return out


def extract_pdf_url(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        if PDF_HOST in a["href"] and a["href"].lower().endswith(".pdf"):
            return a["href"]
    # fallback: regex over raw HTML
    m = re.search(r"https://storage\.googleapis\.com/proudcity/santaanaca/[^\s\"']+\.pdf", html)
    return m.group(0) if m else None


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    s = session()

    sources: list[Source] = []

    # A. Major Projects HTML
    logger.info("Fetching major projects HTML")
    major_path = RAW_DIR / "major-projects.html"
    html = fetch_text(s, MAJOR_URL)
    if html:
        major_path.write_text(html, encoding="utf-8")
        sources.append(
            Source(
                kind="major",
                url=MAJOR_URL,
                pdf_url=None,
                local_path=str(major_path.relative_to(ROOT)),
                sha256=sha256_of(major_path),
                size_bytes=major_path.stat().st_size,
                title="Major Planning Projects (HTML table)",
                period_label=None,
            )
        )
    time.sleep(POLITE_DELAY)

    # B. Monthly wrapper pages -> PDFs
    logger.info("Discovering monthly wrapper pages")
    wrappers = discover_monthly_wrappers(s)
    logger.info("Found %d monthly wrapper pages", len(wrappers))

    for wrap_url, label in wrappers:
        time.sleep(POLITE_DELAY)
        pdf_local = RAW_DIR / f"{label}.pdf"
        if pdf_local.exists() and pdf_local.stat().st_size > 1024:
            logger.info("cached %s", pdf_local.name)
            sources.append(
                Source(
                    kind="monthly",
                    url=wrap_url,
                    pdf_url=None,
                    local_path=str(pdf_local.relative_to(ROOT)),
                    sha256=sha256_of(pdf_local),
                    size_bytes=pdf_local.stat().st_size,
                    title=f"Accepted Development Projects, {label.replace('-', ' ').title()}",
                    period_label=label,
                )
            )
            continue

        wrap_html = fetch_text(s, wrap_url)
        if not wrap_html:
            continue
        pdf_url = extract_pdf_url(wrap_html)
        if not pdf_url:
            logger.warning("no PDF link in %s", wrap_url)
            continue

        time.sleep(POLITE_DELAY)
        if not fetch_bytes(s, pdf_url, pdf_local):
            logger.warning("failed to fetch %s", pdf_url)
            continue
        logger.info("OK %s (%d bytes)", pdf_local.name, pdf_local.stat().st_size)
        sources.append(
            Source(
                kind="monthly",
                url=wrap_url,
                pdf_url=pdf_url,
                local_path=str(pdf_local.relative_to(ROOT)),
                sha256=sha256_of(pdf_local),
                size_bytes=pdf_local.stat().st_size,
                title=f"Accepted Development Projects, {label.replace('-', ' ').title()}",
                period_label=label,
            )
        )

    sources.sort(key=lambda r: (r.kind, r.period_label or ""))
    MANIFEST_PATH.write_text(json.dumps([asdict(r) for r in sources], indent=2))
    logger.info("Wrote manifest with %d sources", len(sources))
    return 0


if __name__ == "__main__":
    sys.exit(main())
