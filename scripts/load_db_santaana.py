"""Load parsed Santa Ana rows into the existing SQLite DB.

- Inserts a `cities` row for Santa Ana, CA if absent.
- For each source in parsed_santaana.json, upserts into `sources`.
- For each row, upserts into `projects`. Dedup key: (city_id, address, project_name)
  via case_number = synthesized slug. The schema enforces UNIQUE(city_id, case_number, address).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "city-planning.sqlite"
PARSED_PATH = ROOT / "data" / "parsed_santaana.json"
MANIFEST_PATH = ROOT / "data" / "raw" / "santaana" / "manifest.json"

logger = logging.getLogger("santaana_load")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CITY_NAME = "Santa Ana"
CITY_STATE = "CA"
CITY_SLUG = "santa-ana-ca"
SANTA_ANA_BASE = "https://www.santa-ana.org"

STATUS_MAP = {
    "under construction": "approved",
    "construction completed": "approved",
    "permits issued": "approved",
    "building plan check": "approved",
    "plan check review": "approved",
    "demolition started": "approved",
    "construction of podium": "approved",
    "entitlements approved": "approved",
    "development project review": "in_process",
    "public hearing": "in_process",
    "n/a": "unknown",
    "": "unknown",
}


def normalize_status(raw: str) -> str:
    if not raw:
        return "in_process"  # accepted but unstated -> in process
    key = raw.strip().lower()
    if key in STATUS_MAP:
        return STATUS_MAP[key]
    # Heuristics
    if "construction" in key or "permit" in key or "approved" in key or "plan check" in key:
        return "approved"
    if "review" in key or "hearing" in key or "pending" in key:
        return "in_process"
    if "withdrawn" in key:
        return "withdrawn"
    if "complete" in key or "final" in key:
        return "completed"
    return "unknown"


def slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s[:80] or "x"


def parse_date(d: str) -> str | None:
    if not d:
        return None
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", d)
    if m:
        mo, day, yr = (int(x) for x in m.groups())
        if yr < 100:
            yr += 2000
        return f"{yr:04d}-{mo:02d}-{day:02d}"
    return d


def period_label_to_date(label: str | None) -> str | None:
    if not label:
        return None
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }
    m = re.match(r"([a-z]+)-(\d{4})", label)
    if not m:
        return None
    mo = months.get(m.group(1).lower())
    yr = int(m.group(2))
    if not mo:
        return None
    last_day = {1:31,2:28,3:31,4:30,5:31,6:30,7:31,8:31,9:30,10:31,11:30,12:31}[mo]
    return f"{yr:04d}-{mo:02d}-{last_day:02d}"


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
    period_end: str | None,
    sha256: str | None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = con.execute("SELECT id FROM sources WHERE url = ?", (url,))
    row = cur.fetchone()
    if row:
        con.execute(
            """UPDATE sources SET title=?, report_period_end=?, published_date=?, sha256=?
               WHERE id=?""",
            (title, period_end, period_end, sha256, row[0]),
        )
        return row[0]
    cur = con.execute(
        """INSERT INTO sources
             (city_id, url, title, report_period_start, report_period_end,
              published_date, fetched_at, sha256)
           VALUES (?,?,?,?,?,?,?,?)""",
        (city_id, url, title, None, period_end, period_end, now, sha256),
    )
    return cur.lastrowid


def upsert_project(
    con: sqlite3.Connection,
    city_id: int,
    source_id: int,
    source_date: str | None,
    case_number: str,
    row: dict,
) -> str:
    address = row.get("address") or ""
    name = row.get("project_name") or ""
    description = row.get("description") or name
    status = normalize_status(row.get("status_raw") or "")

    cur = con.execute(
        "SELECT id, last_seen_date FROM projects WHERE city_id=? AND case_number=? AND address=?",
        (city_id, case_number, address),
    )
    existing = cur.fetchone()

    if existing is None:
        # Fall-through dedup: same name + same address regardless of synth case.
        cur = con.execute(
            """SELECT id FROM projects
               WHERE city_id=? AND address=? AND COALESCE(description,'')=? LIMIT 1""",
            (city_id, address, description),
        )
        existing = cur.fetchone()

    if existing is None and name:
        cur = con.execute(
            """SELECT id FROM projects
               WHERE city_id=? AND address=? AND
                     (description=? OR description LIKE ?) LIMIT 1""",
            (city_id, address, name, f"{name}%"),
        )
        existing = cur.fetchone()

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
                city_id, case_number, address, description,
                row.get("applicant") or "",
                "",
                "",
                "",
                "",
                row.get("district") or "",
                "",
                status,
                row.get("status_raw") or "",
                "",
                row.get("owner") or "",
                source_id, source_id, source_date, source_date,
            ),
        )
        return "inserted"

    pid = existing[0] if not isinstance(existing, tuple) or len(existing) == 1 else existing[0]
    last_seen = existing[1] if isinstance(existing, tuple) and len(existing) > 1 else None
    con.execute(
        """UPDATE projects SET
             description=COALESCE(NULLIF(?, ''), description),
             applicant_name=COALESCE(NULLIF(?, ''), applicant_name),
             district=COALESCE(NULLIF(?, ''), district),
             property_owner=COALESCE(NULLIF(?, ''), property_owner),
             status=?,
             section=COALESCE(NULLIF(?, ''), section),
             last_seen_source_id=?,
             last_seen_date=?
           WHERE id=?""",
        (
            description,
            row.get("applicant") or "",
            row.get("district") or "",
            row.get("owner") or "",
            status,
            row.get("status_raw") or "",
            source_id,
            source_date or last_seen,
            pid,
        ),
    )
    return "updated"


def main() -> int:
    if not PARSED_PATH.exists():
        logger.error("Missing %s", PARSED_PATH)
        return 1

    docs = json.loads(PARSED_PATH.read_text())
    manifest = {}
    if MANIFEST_PATH.exists():
        for r in json.loads(MANIFEST_PATH.read_text()):
            manifest[r["url"]] = r

    con = sqlite3.connect(DB_PATH)
    city_id = upsert_city(con)

    inserted = 0
    updated = 0
    skipped = 0

    # Sort major first (so its richer status/owner data wins for dedupe), then monthly oldest->newest.
    docs.sort(key=lambda d: (0 if d["kind"] == "major" else 1, d.get("period_label") or ""))

    for doc in docs:
        man = manifest.get(doc["source_url"], {})
        period_end = period_label_to_date(doc.get("period_label"))
        title = doc.get("title") or doc.get("local_path", "")
        source_id = upsert_source(con, city_id, doc["source_url"], title, period_end, man.get("sha256"))

        for idx, r in enumerate(doc["rows"]):
            if not r.get("address") and not r.get("project_name"):
                skipped += 1
                continue
            if doc["kind"] == "major":
                # Use project page slug from source_link.
                link = r.get("source_link") or ""
                slug = link.strip("/").split("/")[-1] if link else slugify(r.get("project_name") or "")
                case_number = f"SA-MAJOR-{slug}"
            else:
                period = doc.get("period_label") or "x"
                case_number = f"SA-{period}-{idx+1:02d}"

            row = dict(r)
            # Source link absolutization for major rows.
            if doc["kind"] == "major" and row.get("source_link", "").startswith("/"):
                row["source_link"] = SANTA_ANA_BASE + row["source_link"]

            # Date for monthly rows: prefer per-row date_accepted, fall back to period.
            row_date = parse_date(row.get("date_accepted") or "") or period_end

            res = upsert_project(con, city_id, source_id, row_date, case_number, row)
            if res == "inserted":
                inserted += 1
            elif res == "updated":
                updated += 1
            else:
                skipped += 1

    con.commit()
    total = con.execute("SELECT COUNT(*) FROM projects WHERE city_id=?", (city_id,)).fetchone()[0]
    sources_n = con.execute("SELECT COUNT(*) FROM sources WHERE city_id=?", (city_id,)).fetchone()[0]
    con.close()

    logger.info(
        "Santa Ana: inserted=%d updated=%d skipped=%d total=%d sources=%d",
        inserted, updated, skipped, total, sources_n,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
