"""Export SQLite data to web/public/data/{projects,meta}.json.

Output:
- projects.json: array of project rows (full, but description trimmed to 800 chars
  if needed to keep payload small).
- meta.json: { cities: [...], counts: {...}, generated_at: "..." }
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "city-planning.sqlite"
WEB_DATA = ROOT / "web" / "public" / "data"
PROJECTS_OUT = WEB_DATA / "projects.json"
META_OUT = WEB_DATA / "meta.json"

logger = logging.getLogger("export")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DESC_LIMIT = 800


def main() -> int:
    if not DB_PATH.exists():
        logger.error("DB not found: %s", DB_PATH)
        return 1

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    cities = [dict(r) for r in con.execute("SELECT id, name, state, slug FROM cities ORDER BY name")]

    sources = {}
    for r in con.execute("SELECT id, city_id, url, title, report_period_start, report_period_end, published_date FROM sources"):
        sources[r["id"]] = dict(r)

    projects = []
    for r in con.execute(
        """SELECT p.id, p.city_id, p.case_number, p.address, p.description,
                  p.applicant_name, p.applicant_address, p.applicant_phone, p.applicant_email,
                  p.planner_initials, p.district, p.hearing_body, p.status, p.section,
                  p.zone, p.property_owner, p.latitude, p.longitude,
                  p.first_seen_source_id, p.last_seen_source_id,
                  p.first_seen_date, p.last_seen_date,
                  c.slug AS city_slug, c.name AS city_name, c.state AS city_state
           FROM projects p JOIN cities c ON c.id = p.city_id
           ORDER BY p.last_seen_date DESC, p.id"""
    ):
        d = dict(r)
        if d.get("description") and len(d["description"]) > DESC_LIMIT:
            d["description"] = d["description"][:DESC_LIMIT].rstrip() + "…"
        first_src = sources.get(d.pop("first_seen_source_id"))
        last_src = sources.get(d.pop("last_seen_source_id"))
        d["first_source_url"] = first_src["url"] if first_src else None
        d["last_source_url"] = last_src["url"] if last_src else None
        d["last_source_title"] = last_src["title"] if last_src else None
        projects.append(d)

    counts = {
        "total": len(projects),
        "geocoded": sum(1 for p in projects if p.get("latitude") is not None),
        "by_status": {},
        "by_year": {},
    }
    for p in projects:
        st = p.get("status") or "unknown"
        counts["by_status"][st] = counts["by_status"].get(st, 0) + 1
        ld = p.get("last_seen_date") or ""
        if len(ld) >= 4 and ld[:4].isdigit():
            yr = ld[:4]
            counts["by_year"][yr] = counts["by_year"].get(yr, 0) + 1

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cities": cities,
        "counts": counts,
        "sources": list(sources.values()),
    }

    WEB_DATA.mkdir(parents=True, exist_ok=True)
    PROJECTS_OUT.write_text(json.dumps(projects, ensure_ascii=False))
    META_OUT.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    size_mb = PROJECTS_OUT.stat().st_size / (1024 * 1024)
    logger.info(
        "Wrote %d projects (%.2f MB), %d geocoded (%.1f%%)",
        counts["total"], size_mb, counts["geocoded"],
        (counts["geocoded"] / counts["total"] * 100.0) if counts["total"] else 0,
    )
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
