"""Geocode project addresses via Nominatim (OpenStreetMap).

- 1 request per second hard rate limit
- Custom User-Agent
- Cache results in `geocode_cache` table
- Misses logged to data/geocode_misses.log
- Garden Grove projects get ", Garden Grove, CA" appended if not present.

Strategy: clean each raw address (collapse whitespace, drop "at the corner of",
keep the first numbered street segment if present), then ask Nominatim.
If the cleaned form fails, retry with a stripped form (just the numbered street
+ ", Garden Grove, CA").
"""

from __future__ import annotations

import logging
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "city-planning.sqlite"
MISS_LOG = ROOT / "data" / "geocode_misses.log"

logger = logging.getLogger("geocode")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

UA = "city-planning-explorer/0.1 (https://github.com/kpx-dev/city-planning; kien@kienpham.com)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
RATE_DELAY = 1.05

CITY_BOUNDS = "33.7, -118.05, 33.83, -117.85"  # Garden Grove area, S,W,N,E

ADDR_PREFIXES = re.compile(
    r"^(?:northeast|northwest|southeast|southwest|north|south|east|west)?\s*"
    r"(?:corner of|side of|along)\s+",
    re.IGNORECASE,
)
AT_PHRASE = re.compile(r"\bat\s+(\d{1,6}[A-Za-z]?\s+[^,;]+)", re.IGNORECASE)
NUM_STREET = re.compile(r"\b(\d{1,6}[A-Za-z]?)\s+([A-Za-z][A-Za-z0-9.\s]+?(?:\s+(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Way|Ln|Lane|Ct|Court|Pl|Place|Hwy|Highway|Pkwy|Parkway|Cir|Circle))\b)",
    re.IGNORECASE,
)


def normalize_for_geocode(raw: str) -> tuple[str, str | None]:
    """Returns (primary_query, fallback_query). Both include city/state."""
    if not raw:
        return ("", None)
    s = re.sub(r"\s+", " ", raw).strip().rstrip(".,")

    # If text mentions "at <num street>", prefer that.
    m = AT_PHRASE.search(s)
    if m:
        s = m.group(1).strip().rstrip(".,")

    s = ADDR_PREFIXES.sub("", s).strip()

    fallback = None
    m = NUM_STREET.search(s)
    if m:
        fallback = f"{m.group(1)} {m.group(2).strip()}, Garden Grove, CA"

    if "garden grove" not in s.lower():
        primary = f"{s}, Garden Grove, CA"
    else:
        primary = s
    return (primary, fallback if fallback != primary else None)


def init_cache(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS geocode_cache (
          raw_address TEXT PRIMARY KEY,
          query TEXT,
          latitude REAL,
          longitude REAL,
          display_name TEXT,
          fetched_at TEXT NOT NULL,
          source TEXT
        );
        """
    )


def cache_get(con: sqlite3.Connection, raw: str) -> tuple[float, float] | None | str:
    """Returns (lat, lon) on hit, None on miss, or 'tried' if previously failed."""
    cur = con.execute(
        "SELECT latitude, longitude FROM geocode_cache WHERE raw_address=?", (raw,)
    )
    row = cur.fetchone()
    if not row:
        return None
    if row[0] is None:
        return "tried"
    return (row[0], row[1])


def cache_put(
    con: sqlite3.Connection,
    raw: str,
    query: str,
    lat: float | None,
    lon: float | None,
    display: str | None,
    source: str,
) -> None:
    con.execute(
        """INSERT INTO geocode_cache
             (raw_address, query, latitude, longitude, display_name, fetched_at, source)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(raw_address) DO UPDATE SET
             query=excluded.query,
             latitude=excluded.latitude,
             longitude=excluded.longitude,
             display_name=excluded.display_name,
             fetched_at=excluded.fetched_at,
             source=excluded.source""",
        (raw, query, lat, lon, display, datetime.now(timezone.utc).isoformat(), source),
    )


_last_call = 0.0


def nominatim_search(s: requests.Session, query: str) -> dict | None:
    global _last_call
    delta = time.monotonic() - _last_call
    if delta < RATE_DELAY:
        time.sleep(RATE_DELAY - delta)
    _last_call = time.monotonic()
    try:
        r = s.get(
            NOMINATIM,
            params={
                "q": query,
                "format": "json",
                "limit": 1,
                "addressdetails": 1,
                "countrycodes": "us",
            },
            timeout=20,
        )
        if r.status_code != 200:
            return None
        arr = r.json()
        if not arr:
            return None
        return arr[0]
    except Exception as e:
        logger.warning("nominatim error for %r: %s", query, e)
        return None


def main() -> int:
    if not DB_PATH.exists():
        logger.error("DB not found: %s", DB_PATH)
        return 1
    con = sqlite3.connect(DB_PATH)
    init_cache(con)

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en"})

    cur = con.execute(
        """SELECT id, address FROM projects
           WHERE (latitude IS NULL OR longitude IS NULL)
           AND COALESCE(address, '') <> ''"""
    )
    rows = cur.fetchall()
    logger.info("Need geocoding for %d projects", len(rows))

    misses: list[str] = []
    hit = 0
    miss = 0
    cached = 0

    for pid, raw in rows:
        primary, fallback = normalize_for_geocode(raw)
        if not primary:
            misses.append(raw)
            miss += 1
            continue

        cached_val = cache_get(con, raw)
        if isinstance(cached_val, tuple):
            con.execute("UPDATE projects SET latitude=?, longitude=? WHERE id=?", (*cached_val, pid))
            cached += 1
            continue
        if cached_val == "tried":
            misses.append(raw)
            miss += 1
            continue

        result = nominatim_search(s, primary)
        used_query = primary
        if not result and fallback:
            result = nominatim_search(s, fallback)
            used_query = fallback

        if result:
            try:
                lat = float(result["lat"])
                lon = float(result["lon"])
                # Sanity-check we are roughly in Orange County / Garden Grove area.
                if not (33.5 < lat < 34.1 and -118.3 < lon < -117.5):
                    logger.info("OUT-OF-AREA %r -> %s,%s display=%s", raw, lat, lon, result.get("display_name"))
                    cache_put(con, raw, used_query, None, None, result.get("display_name"), "out_of_area")
                    misses.append(raw)
                    miss += 1
                    continue
                cache_put(con, raw, used_query, lat, lon, result.get("display_name"), "nominatim")
                con.execute("UPDATE projects SET latitude=?, longitude=? WHERE id=?", (lat, lon, pid))
                hit += 1
                if hit % 25 == 0:
                    con.commit()
                    logger.info("Geocoded %d so far (miss %d)", hit, miss)
            except (KeyError, ValueError, TypeError):
                cache_put(con, raw, used_query, None, None, None, "bad_response")
                misses.append(raw)
                miss += 1
        else:
            cache_put(con, raw, used_query, None, None, None, "no_result")
            misses.append(raw)
            miss += 1

    con.commit()

    total = con.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    geocoded = con.execute(
        "SELECT COUNT(*) FROM projects WHERE latitude IS NOT NULL"
    ).fetchone()[0]
    con.close()

    if misses:
        MISS_LOG.write_text("\n".join(misses))

    pct = (geocoded / total * 100.0) if total else 0
    logger.info(
        "Done. Hits=%d Misses=%d CachedHits=%d. DB: %d/%d projects geocoded (%.1f%%)",
        hit, miss, cached, geocoded, total, pct,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
