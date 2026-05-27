"""Load parsed DPU rows into SQLite.

Schema is multi-city ready: cities, sources, projects.
Dedup key is (city_id, case_number, normalized_address). When the same case
appears in multiple PDFs (sources), we keep the latest description/status and
update last_seen_*.

Run:
    python scripts/load_db.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARSED_PATH = ROOT / "data" / "parsed.json"
MANIFEST_PATH = ROOT / "data" / "raw" / "manifest.json"
DB_PATH = ROOT / "data" / "city-planning.sqlite"

logger = logging.getLogger("load")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CITY_NAME = "Garden Grove"
CITY_STATE = "CA"
CITY_SLUG = "garden-grove-ca"


SCHEMA = """
CREATE TABLE IF NOT EXISTS cities (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  state TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  city_id INTEGER REFERENCES cities(id),
  url TEXT UNIQUE NOT NULL,
  title TEXT,
  report_period_start TEXT,
  report_period_end TEXT,
  published_date TEXT,
  fetched_at TEXT NOT NULL,
  sha256 TEXT
);

CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  city_id INTEGER REFERENCES cities(id),
  case_number TEXT,
  address TEXT,
  description TEXT,
  applicant_name TEXT,
  applicant_address TEXT,
  applicant_phone TEXT,
  applicant_email TEXT,
  planner_initials TEXT,
  district TEXT,
  hearing_body TEXT,
  status TEXT,
  section TEXT,
  zone TEXT,
  property_owner TEXT,
  latitude REAL,
  longitude REAL,
  first_seen_source_id INTEGER REFERENCES sources(id),
  last_seen_source_id INTEGER REFERENCES sources(id),
  first_seen_date TEXT,
  last_seen_date TEXT,
  UNIQUE(city_id, case_number, address)
);

CREATE INDEX IF NOT EXISTS idx_projects_city ON projects(city_id);
CREATE INDEX IF NOT EXISTS idx_projects_case ON projects(case_number);

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


STATUS_LEGEND_MID = {
    "1": "in_process",
    "2": "in_process",
    "3": "approved",
    "4": "approved",
    "5": "approved",
    "6": "approved",
    "7": "completed",
    "8": "withdrawn",
    "9": "in_process",
}


def normalize_status(raw_status: str, section: str) -> str:
    if raw_status:
        rs = raw_status.strip()
        if rs in STATUS_LEGEND_MID:
            return STATUS_LEGEND_MID[rs]
    if section:
        s = section.upper()
        if "IN PROCESS" in s:
            return "in_process"
        if "APPROVED" in s or "ENTITLEMENT" in s:
            return "approved"
        if "WITHDRAWN" in s:
            return "withdrawn"
        if "COMPLETED" in s or "FINAL" in s or "PERMIT COMPLETE" in s:
            return "completed"
        if "UNDER CONSTRUCTION" in s:
            return "approved"
    return "unknown"


def normalize_address(addr: str) -> str:
    if not addr:
        return ""
    a = re.sub(r"\s+", " ", addr).strip().lower()
    a = re.sub(r"[.,]+$", "", a)
    return a


def derive_published_date(quarter: str | None, period_end: str | None) -> str | None:
    if quarter:
        m = re.match(r"Q(\d)\s+(\d{4})", quarter)
        if m:
            q, yr = int(m.group(1)), int(m.group(2))
            month_end = {1: 3, 2: 6, 3: 9, 4: 12}[q]
            day = {3: 31, 6: 30, 9: 30, 12: 31}[month_end]
            return f"{yr}-{month_end:02d}-{day:02d}"
    return period_end


def upsert_city(con: sqlite3.Connection) -> int:
    cur = con.execute("SELECT id FROM cities WHERE slug = ?", (CITY_SLUG,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur = con.execute(
        "INSERT INTO cities (name, state, slug) VALUES (?, ?, ?)",
        (CITY_NAME, CITY_STATE, CITY_SLUG),
    )
    return cur.lastrowid


def upsert_source(
    con: sqlite3.Connection,
    city_id: int,
    url: str,
    title: str,
    period_start: str | None,
    period_end: str | None,
    published_date: str | None,
    sha256: str | None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = con.execute("SELECT id FROM sources WHERE url = ?", (url,))
    row = cur.fetchone()
    if row:
        con.execute(
            """UPDATE sources SET
                 title=?, report_period_start=?, report_period_end=?,
                 published_date=?, sha256=?
               WHERE id=?""",
            (title, period_start, period_end, published_date, sha256, row[0]),
        )
        return row[0]
    cur = con.execute(
        """INSERT INTO sources
             (city_id, url, title, report_period_start, report_period_end,
              published_date, fetched_at, sha256)
           VALUES (?,?,?,?,?,?,?,?)""",
        (city_id, url, title, period_start, period_end, published_date, now, sha256),
    )
    return cur.lastrowid


def upsert_project(con: sqlite3.Connection, city_id: int, source_id: int, source_date: str | None, row: dict) -> str:
    """Returns 'inserted' or 'updated'."""
    case = (row.get("case_number") or "").strip()
    addr = normalize_address(row.get("address") or "")
    if not case and not addr:
        return "skipped"

    status = normalize_status(row.get("status") or "", row.get("section") or "")

    cur = con.execute(
        "SELECT id, last_seen_date FROM projects WHERE city_id=? AND case_number=? AND address=?",
        (city_id, case, row.get("address") or ""),
    )
    existing = cur.fetchone()

    if existing is None:
        # Try a softer match by normalized address.
        cur = con.execute(
            """SELECT id, last_seen_date, address FROM projects
               WHERE city_id=? AND case_number=?""",
            (city_id, case),
        )
        for pid, last_seen, ex_addr in cur.fetchall():
            if normalize_address(ex_addr or "") == addr:
                existing = (pid, last_seen)
                break

    if existing is None:
        con.execute(
            """INSERT INTO projects
                 (city_id, case_number, address, description, applicant_name,
                  applicant_address, applicant_phone, applicant_email,
                  planner_initials, district, hearing_body, status, section,
                  zone, property_owner, first_seen_source_id, last_seen_source_id,
                  first_seen_date, last_seen_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                city_id, case, row.get("address") or "", row.get("description") or "",
                row.get("applicant_name") or "", row.get("applicant_address") or "",
                row.get("applicant_phone") or "", row.get("applicant_email") or "",
                row.get("planner_initials") or "", row.get("district") or "",
                row.get("hearing_body") or "", status, row.get("section") or "",
                row.get("zone") or "", row.get("property_owner") or "",
                source_id, source_id, source_date, source_date,
            ),
        )
        return "inserted"

    pid, last_seen = existing
    update_fields = (
        row.get("description") or "",
        row.get("applicant_name") or "",
        row.get("applicant_address") or "",
        row.get("applicant_phone") or "",
        row.get("applicant_email") or "",
        row.get("planner_initials") or "",
        row.get("district") or "",
        row.get("hearing_body") or "",
        status,
        row.get("section") or "",
        row.get("zone") or "",
        row.get("property_owner") or "",
        source_id,
        source_date or last_seen,
        pid,
    )
    con.execute(
        """UPDATE projects SET
             description=COALESCE(NULLIF(?, ''), description),
             applicant_name=COALESCE(NULLIF(?, ''), applicant_name),
             applicant_address=COALESCE(NULLIF(?, ''), applicant_address),
             applicant_phone=COALESCE(NULLIF(?, ''), applicant_phone),
             applicant_email=COALESCE(NULLIF(?, ''), applicant_email),
             planner_initials=COALESCE(NULLIF(?, ''), planner_initials),
             district=COALESCE(NULLIF(?, ''), district),
             hearing_body=COALESCE(NULLIF(?, ''), hearing_body),
             status=?,
             section=COALESCE(NULLIF(?, ''), section),
             zone=COALESCE(NULLIF(?, ''), zone),
             property_owner=COALESCE(NULLIF(?, ''), property_owner),
             last_seen_source_id=?,
             last_seen_date=?
           WHERE id=?""",
        update_fields,
    )
    return "updated"


def main() -> int:
    if not PARSED_PATH.exists():
        logger.error("Parsed file not found: %s", PARSED_PATH)
        return 1
    docs = json.loads(PARSED_PATH.read_text())

    manifest_by_url: dict[str, dict] = {}
    if MANIFEST_PATH.exists():
        for r in json.loads(MANIFEST_PATH.read_text()):
            manifest_by_url[r["url"]] = r

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    city_id = upsert_city(con)

    sort_key = lambda d: (d.get("report_period_end") or "", d.get("quarter") or "", d.get("source_url"))
    docs.sort(key=sort_key)

    inserted = 0
    updated = 0
    skipped = 0

    for doc in docs:
        url = doc["source_url"]
        man = manifest_by_url.get(url, {})
        published_date = derive_published_date(doc.get("quarter"), doc.get("report_period_end"))
        title = Path(doc.get("local_path") or url).name
        source_id = upsert_source(
            con,
            city_id,
            url,
            title,
            doc.get("report_period_start"),
            doc.get("report_period_end"),
            published_date,
            man.get("sha256"),
        )

        for r in doc.get("rows", []):
            result = upsert_project(con, city_id, source_id, published_date, r)
            if result == "inserted":
                inserted += 1
            elif result == "updated":
                updated += 1
            else:
                skipped += 1

    con.commit()
    total = con.execute("SELECT COUNT(*) FROM projects WHERE city_id=?", (city_id,)).fetchone()[0]
    sources_n = con.execute("SELECT COUNT(*) FROM sources WHERE city_id=?", (city_id,)).fetchone()[0]
    con.close()

    logger.info(
        "Loaded: inserted=%d updated=%d skipped=%d -> %d unique projects across %d sources",
        inserted, updated, skipped, total, sources_n,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
