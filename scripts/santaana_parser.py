"""Parse Santa Ana sources into structured rows.

Inputs:
  data/raw/santaana/manifest.json
  data/raw/santaana/major-projects.html
  data/raw/santaana/<month>-<year>.pdf

Output:
  data/parsed_santaana.json
    [{ source_url, kind, period_label, local_path, rows: [...] }, ...]

Row schema (matches what load_db_santaana.py expects):
  project_name, address, district, applicant, owner, status_raw,
  application_type, description, date_accepted, source_link
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "santaana"
MANIFEST = RAW_DIR / "manifest.json"
OUT_PATH = ROOT / "data" / "parsed_santaana.json"

logger = logging.getLogger("santaana_parse")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

WARD_RE = re.compile(r"\(?\s*ward\s*(\d{1,2})\s*\)?", re.IGNORECASE)
WARD_DASH_RE = re.compile(r"[\s\-–—]+ward\s*(\d{1,2})", re.IGNORECASE)


@dataclass
class Row:
    project_name: str = ""
    address: str = ""
    district: str = ""
    applicant: str = ""
    owner: str = ""
    status_raw: str = ""
    application_type: str = ""
    description: str = ""
    date_accepted: str = ""
    source_link: str = ""


@dataclass
class ParsedSource:
    source_url: str
    kind: str
    period_label: str | None
    local_path: str
    title: str
    rows: list[Row] = field(default_factory=list)


def normalize(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.replace("\n", " ")).strip()


def split_address_ward(raw: str) -> tuple[str, str]:
    """Return (address, district)."""
    if not raw:
        return ("", "")
    s = normalize(raw)
    # Try "(Ward N)"
    m = WARD_RE.search(s)
    if m:
        ward = m.group(1)
        s = s[: m.start()].rstrip(" ,()-–—")
        return (s, ward)
    # Try "<addr> – Ward N"
    m = WARD_DASH_RE.search(s)
    if m:
        ward = m.group(1)
        s = s[: m.start()].rstrip(" ,-–—")
        return (s, ward)
    return (s, "")


def parse_major_html(path: Path) -> list[Row]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    tables = soup.find_all("table")
    if not tables:
        return []
    table = tables[0]
    rows: list[Row] = []
    trs = table.find_all("tr")
    for tr in trs[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 5:
            continue
        name_cell = cells[0]
        link = name_cell.find("a")
        source_link = link["href"] if link and link.has_attr("href") else ""
        name = name_cell.get_text(" ", strip=True)
        addr_raw = cells[1].get_text(" ", strip=True)
        applicant = cells[2].get_text(" ", strip=True)
        owner = cells[3].get_text(" ", strip=True)
        status = cells[4].get_text(" ", strip=True)
        addr, ward = split_address_ward(addr_raw)
        rows.append(
            Row(
                project_name=name,
                address=addr,
                district=ward,
                applicant=applicant,
                owner=owner,
                status_raw=status,
                description=name,
                source_link=source_link,
            )
        )
    return rows


def parse_monthly_pdf(path: Path) -> list[Row]:
    import pdfplumber

    rows: list[Row] = []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages):
            for table in page.extract_tables():
                if not table:
                    continue
                # Find header row index (it usually is index 0).
                header_idx = -1
                for i, r in enumerate(table[:3]):
                    j = " ".join((c or "") for c in r).lower()
                    if "project name" in j and "applicant" in j:
                        header_idx = i
                        break
                if header_idx < 0:
                    continue
                header = [normalize(c).lower() for c in table[header_idx]]
                # Map columns by keyword.
                col = {}
                for i, h in enumerate(header):
                    if "project name" in h and "name" not in col:
                        col["name"] = i
                    elif "applicant" in h and "applicant" not in col:
                        col["applicant"] = i
                    elif "owner" in h and "owner" not in col:
                        col["owner"] = i
                    elif "address" in h and "address" not in col:
                        col["address"] = i
                    elif "application" in h and "type" in h:
                        col["app_type"] = i
                    elif "description" in h and "desc" not in col:
                        col["desc"] = i
                    elif "date" in h and "date" not in col:
                        col["date"] = i
                if "name" not in col or "address" not in col:
                    continue
                for r in table[header_idx + 1 :]:
                    if not r or len(r) < 4:
                        continue
                    name = normalize(r[col.get("name", 0)])
                    if not name or name.lower().startswith("project name"):
                        continue
                    addr_raw = normalize(r[col.get("address", 3)] or "")
                    addr, ward = split_address_ward(addr_raw)
                    applicant = normalize(r[col.get("applicant", 1)] or "")
                    owner = normalize(r[col.get("owner", 2)] or "")
                    app_type = normalize(r[col.get("app_type", -1)] or "") if "app_type" in col else ""
                    desc = normalize(r[col.get("desc", -1)] or "") if "desc" in col else ""
                    date_acc = normalize(r[col.get("date", -1)] or "") if "date" in col else ""
                    rows.append(
                        Row(
                            project_name=name,
                            address=addr,
                            district=ward,
                            applicant=applicant,
                            owner=owner,
                            status_raw="",
                            application_type=app_type,
                            description=desc or name,
                            date_accepted=date_acc,
                        )
                    )
    return rows


def main() -> int:
    if not MANIFEST.exists():
        logger.error("Manifest missing: %s", MANIFEST)
        return 1
    sources = json.loads(MANIFEST.read_text())

    parsed: list[dict] = []
    total_rows = 0

    for src in sources:
        local = ROOT / src["local_path"]
        if not local.exists():
            logger.warning("missing local file: %s", local)
            continue
        if src["kind"] == "major":
            rows = parse_major_html(local)
        else:
            rows = parse_monthly_pdf(local)
        logger.info("%s -> %d rows", local.name, len(rows))
        total_rows += len(rows)
        parsed.append(
            {
                "source_url": src["url"],
                "kind": src["kind"],
                "period_label": src.get("period_label"),
                "local_path": src["local_path"],
                "title": src.get("title", ""),
                "rows": [asdict(r) for r in rows],
            }
        )

    OUT_PATH.write_text(json.dumps(parsed, indent=2, ensure_ascii=False))
    logger.info("Wrote %s with %d sources, %d total rows", OUT_PATH, len(parsed), total_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
