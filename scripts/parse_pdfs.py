"""Parse Garden Grove DPU PDFs into structured rows.

The DPUs span at least three layout generations:
  * 2014–2016 (dpu011514, dpu041515): visible table borders. Columns =
    CASE NO / SITE ADDRESS AND LOCATION / PROJECT DESCRIPTION (CEQA REQ) /
    G-P,ZONE / APPLICANT / PROPERTY OWNER / DECISION BODY / PLANNER.
  * 2017–2018 (dpujanuary-march2017, dpujuly-september2018): no table borders.
    Columns = CASE # / SITE ADDRESS / PROJECT DESCRIPTION / APPLICANT / STATUS /
    PLANNER. Status is a number 1..9 with a legend at bottom.
  * 2019+ (dpu*-2019.pdf onward, q1-2026-finalver2.pdf): visible table borders.
    Columns = CASE # / PROJECT ADDRESSES / PROJECT DESCRIPTION / APPLICANT /
    PLANNER / DISTRICTS / HEARING BODY. Projects grouped by section headers like
    "IN PROCESS IN PLANNING DIVISION".

Strategy:
  * Modern + Legacy: use pdfplumber.extract_tables() — borders are present.
  * Mid: position-based extraction using the header line's x-coordinates to define
    column bands, then group multi-line content by case-number anchor on the
    leftmost column.

Errors are appended to data/parse_errors.log; processing continues on failures.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
MANIFEST_PATH = RAW_DIR / "manifest.json"
PARSED_PATH = ROOT / "data" / "parsed.json"
ERR_LOG = ROOT / "data" / "parse_errors.log"

logger = logging.getLogger("parse")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CASE_TOKEN_RE = re.compile(
    r"^(?:CUP|DR|SP|A|GPA|IOU|TE|TT|TPM|PM|V|PUD|HE|VAR|CDP|ZA|ZTC|MND|EIR|AGR|AB|RP|FAR|SD|VTPM|MVUP|VTT|VTM|TM|UP)-",
    re.IGNORECASE,
)
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

REPORT_PERIOD_RE = re.compile(
    r"(?:report\s+is\s+(?:for|current\s+from))\s+([A-Za-z0-9 ,\-]+?)\s+(?:through|to|–|—)\s+([A-Za-z0-9 ,\-]+?)(?:\.|\s*$|\sFor)",
    re.IGNORECASE,
)
QUARTER_RE = re.compile(
    r"This\s+report\s+is\s+for\s+(\d(?:st|nd|rd|th))\s+Quarter\s+(\d{4})",
    re.IGNORECASE,
)

LAYOUT_MODERN = "modern"
LAYOUT_MID = "mid"
LAYOUT_LEGACY = "legacy"

SECTION_RE = re.compile(
    r"^(?:IN\s+PROCESS|ENTITLEMENTS?|AWAITING|RECENTLY|PROJECTS|COMPLETED|APPROVED|WITHDRAWN|UNDER\s+CONSTRUCTION|FINAL(?:ED)?\s|PERMIT\s+COMPLETE)[A-Z\s,&'\-/]*$"
)


@dataclass
class Row:
    case_number: str = ""
    address: str = ""
    description: str = ""
    applicant_block: str = ""
    planner_initials: str = ""
    district: str = ""
    hearing_body: str = ""
    status: str = ""
    section: str = ""
    applicant_name: str = ""
    applicant_address: str = ""
    applicant_phone: str = ""
    applicant_email: str = ""
    zone: str = ""
    property_owner: str = ""


@dataclass
class ParsedDoc:
    source_url: str
    local_path: str
    layout: str
    report_period_start: str | None = None
    report_period_end: str | None = None
    quarter: str | None = None
    rows: list[Row] = field(default_factory=list)


def detect_layout(text: str) -> str:
    up = text.upper()
    if "PROJECT ADDRESSES" in up and "HEARING BODY" in up:
        return LAYOUT_MODERN
    if "DECISION" in up and "BODY" in up and ("CEQA" in up or "PROPERTY OWNER" in up):
        return LAYOUT_LEGACY
    return LAYOUT_MID


def normalize_cell(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.replace("\n", " ")).strip()


def split_applicant(block: str) -> tuple[str, str, str, str]:
    """Return (name, address, phone, email)."""
    if not block:
        return ("", "", "", "")
    em = EMAIL_RE.search(block)
    ph = PHONE_RE.search(block)
    text = block
    if em:
        text = text.replace(em.group(0), " ")
    if ph:
        text = text.replace(ph.group(0), " ")
    text = re.sub(r"\s+", " ", text).strip()

    # Split by separators that look like name/address boundaries.
    name = text
    addr = ""
    # Address heuristic: first chunk that begins with a number is the address.
    m = re.search(r"\b\d{1,6}[A-Z]?\s+\S", text)
    if m:
        name = text[: m.start()].strip().rstrip(",")
        addr = text[m.start():].strip()
    return (name, addr, ph.group(0) if ph else "", em.group(0) if em else "")


def is_section_text(t: str) -> bool:
    if not t or len(t) > 100:
        return False
    if t != t.upper():
        return False
    if any(k in t for k in ("DEVELOPMENT PROJECTS UPDATE", "COMMUNITY DEVELOPMENT", "PLANNING DIVISION AT", "FOR THE MOST RECENT")):
        return False
    if SECTION_RE.match(t):
        return True
    return False


# ---------- Modern + Legacy: extract_tables ----------

def parse_with_extract_tables(pdf, layout: str) -> list[Row]:
    rows: list[Row] = []
    current_section = ""
    for page_no, page in enumerate(pdf.pages):
        # Track section text on this page (looking at extract_text lines).
        page_text = page.extract_text() or ""
        for line in page_text.splitlines():
            ln = line.strip()
            if is_section_text(ln):
                current_section = ln

        tables = page.extract_tables()
        for table in tables:
            if not table or not table[0]:
                continue
            header = [normalize_cell(c) for c in table[0]]
            # Determine if this is a header row vs continuation.
            up_header = " ".join(header).upper()
            has_header_row = "CASE" in up_header and ("APPLICANT" in up_header or "DESCRIPTION" in up_header)
            data_rows = table[1:] if has_header_row else table
            # Compute column index map from the header.
            col_idx = {}
            for i, h in enumerate(header):
                hu = h.upper()
                if "CASE" in hu and "case" not in col_idx:
                    col_idx["case"] = i
                if ("PROJECT ADDRESS" in hu or "SITE ADDRESS" in hu) and "address" not in col_idx:
                    col_idx["address"] = i
                if "PROJECT" in hu and "DESCRIPTION" in hu and "description" not in col_idx:
                    col_idx["description"] = i
                if "APPLICANT" in hu and "applicant" not in col_idx:
                    col_idx["applicant"] = i
                if "PLANNER" in hu and "planner" not in col_idx:
                    col_idx["planner"] = i
                if "DISTRICT" in hu:
                    col_idx["district"] = i
                if "HEARING" in hu and "BODY" in hu:
                    col_idx["hearing_body"] = i
                if "DECISION" in hu and "BODY" in hu:
                    col_idx["hearing_body"] = i
                if "G-P" in hu or "ZONE" in hu:
                    col_idx["zone"] = i
                if "PROPERTY OWNER" in hu:
                    col_idx["owner"] = i
                if hu == "STATUS" or " STATUS" in hu:
                    col_idx["status"] = i
            if "case" not in col_idx and not has_header_row:
                # If there's no header row and we don't know columns, skip.
                continue

            # Default column orders if header row missing (continuation tables).
            if not has_header_row:
                if layout == LAYOUT_MODERN:
                    col_idx = {"case": 0, "address": 1, "description": 3, "applicant": 5, "planner": 6, "district": 7, "hearing_body": 8}
                elif layout == LAYOUT_LEGACY:
                    col_idx = {"case": 0, "address": 1, "description": 2, "zone": 3, "applicant": 4, "owner": 5, "hearing_body": 6, "planner": 7}

            for r in data_rows:
                if not r:
                    continue
                # Normalize length.
                rr = list(r) + [""] * 12
                case = normalize_cell(rr[col_idx.get("case", 0)])
                if not case:
                    continue
                # Skip header rows that may sneak in.
                if case.upper().startswith("CASE"):
                    continue
                # Some rows have just a section title in cell 0; skip.
                if not CASE_TOKEN_RE.match(case.split()[0]):
                    continue
                row = Row(
                    case_number=case,
                    address=normalize_cell(rr[col_idx.get("address", 1)]) if "address" in col_idx else "",
                    description=normalize_cell(rr[col_idx.get("description", 3)]) if "description" in col_idx else "",
                    applicant_block=normalize_cell(rr[col_idx.get("applicant", 5)]) if "applicant" in col_idx else "",
                    planner_initials=normalize_cell(rr[col_idx.get("planner", 6)]) if "planner" in col_idx else "",
                    district=normalize_cell(rr[col_idx.get("district", 7)]) if "district" in col_idx else "",
                    hearing_body=normalize_cell(rr[col_idx.get("hearing_body", 8)]) if "hearing_body" in col_idx else "",
                    status=normalize_cell(rr[col_idx.get("status", -1)]) if "status" in col_idx else "",
                    zone=normalize_cell(rr[col_idx.get("zone", -1)]) if "zone" in col_idx else "",
                    property_owner=normalize_cell(rr[col_idx.get("owner", -1)]) if "owner" in col_idx else "",
                    section=current_section,
                )
                name, addr, phone, email = split_applicant(row.applicant_block)
                row.applicant_name = name
                row.applicant_address = addr
                row.applicant_phone = phone
                row.applicant_email = email
                rows.append(row)
    return rows


# ---------- Mid layout: position-based ----------

def find_mid_columns(words):
    """For 2017-2018 PDFs, identify column x-positions from the header line.

    Header words may straddle two adjacent y-rows because of slight rendering
    offset, so collect words from any line that contains "CASE" plus the next
    couple of lines (within ~6pt) into a single header band.
    """
    lines: dict[int, list] = {}
    for w in words:
        lines.setdefault(round(w["top"]), []).append(w)
    sorted_y = sorted(lines)
    for idx, y in enumerate(sorted_y):
        joined = " ".join(w["text"] for w in lines[y]).upper()
        if "CASE" not in joined:
            continue
        # Combine this and adjacent lines if close (within ~12pt above/below).
        combined = list(lines[y])
        for j in range(idx + 1, min(idx + 5, len(sorted_y))):
            ny = sorted_y[j]
            if ny - y > 12:
                break
            combined.extend(lines[ny])
        for j in range(idx - 1, max(idx - 3, -1), -1):
            ny = sorted_y[j]
            if y - ny > 12:
                break
            combined.extend(lines[ny])
        ws = sorted(combined, key=lambda w: w["x0"])
        joined = " ".join(w["text"] for w in ws).upper()
        if not ("APPLICANT" in joined and "PLANNER" in joined):
            continue

        cols = []
        seen = set()
        for w in ws:
            t = w["text"].upper()
            if t in ("CASE", "#") and "case" not in seen:
                cols.append(("case", w["x0"]))
                seen.add("case")
            elif t == "SITE" and "address" not in seen:
                cols.append(("address", w["x0"]))
                seen.add("address")
            elif t == "PROJECT" and "description" not in seen and "address" in seen:
                cols.append(("description", w["x0"]))
                seen.add("description")
            elif t == "APPLICANT" and "applicant" not in seen:
                cols.append(("applicant", w["x0"]))
                seen.add("applicant")
            elif t == "STATUS" and "status" not in seen:
                cols.append(("status", w["x0"]))
                seen.add("status")
            elif t == "PLANNER" and "planner" not in seen:
                cols.append(("planner", w["x0"]))
                seen.add("planner")
        if len(cols) >= 4:
            return cols
    return []


def parse_mid_layout(pdf) -> list[Row]:
    rows: list[Row] = []
    bands: list[tuple[str, float, float]] = []
    current_section = ""

    for page_no, page in enumerate(pdf.pages):
        words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
        if not words:
            continue

        # Group by line.
        lines: dict[int, list] = {}
        for w in words:
            lines.setdefault(round(w["top"]), []).append(w)
        sorted_lines = [(y, sorted(lines[y], key=lambda w: w["x0"])) for y in sorted(lines)]

        # Refresh bands using this page's header if found; else reuse last bands.
        cols = find_mid_columns(words)
        if cols:
            bands = []
            for i, (name, x0) in enumerate(cols):
                x_min = x0 - 4
                x_max = cols[i + 1][1] - 4 if i + 1 < len(cols) else 1e9
                bands.append((name, x_min, x_max))
        if not bands:
            continue

        # Walk lines, anchor on case-number rows.
        accumulator: dict[str, list[str]] | None = None

        def flush():
            nonlocal accumulator
            if not accumulator:
                return
            row = Row(
                case_number=normalize_cell(" ".join(accumulator.get("case", []))),
                address=normalize_cell(" ".join(accumulator.get("address", []))),
                description=normalize_cell(" ".join(accumulator.get("description", []))),
                applicant_block=normalize_cell(" ".join(accumulator.get("applicant", []))),
                status=normalize_cell(" ".join(accumulator.get("status", []))),
                planner_initials=normalize_cell(" ".join(accumulator.get("planner", []))),
                section=current_section,
            )
            name, addr, phone, email = split_applicant(row.applicant_block)
            row.applicant_name = name
            row.applicant_address = addr
            row.applicant_phone = phone
            row.applicant_email = email
            if row.case_number and (row.address or row.description):
                rows.append(row)
            accumulator = None

        for y, ws in sorted_lines:
            line_text = " ".join(w["text"] for w in ws).strip()
            if not line_text:
                continue
            up = line_text.upper()
            if up.startswith("PAGE "):
                continue
            if "DEVELOPMENT PROJECTS UPDATE" in up:
                continue
            if "PLANNING DIVISION AT" in up:
                continue
            if "ECONOMIC DEVELOPMENT DEPARTMENT" in up or "COMMUNITY DEVELOPMENT DEPARTMENT" in up:
                continue
            if up.startswith("CASE #") or up.startswith("CASE NO"):
                continue
            if up.startswith("STATUS #") or "AWAITING PLANNING COMM" in up or "ENTITLEMENTS GRANTED" in up and "AWAITING" in up:
                continue
            if "AWAITING ZONING ADMIN" in up or "AWAITING DIRECTOR" in up:
                continue

            if is_section_text(line_text):
                flush()
                current_section = line_text
                continue

            # Build per-column buckets.
            by_col: dict[str, list[str]] = {}
            for w in ws:
                cx = (w["x0"] + w["x1"]) / 2
                for name, x_min, x_max in bands:
                    if x_min <= cx < x_max:
                        by_col.setdefault(name, []).append(w["text"])
                        break

            case_text = " ".join(by_col.get("case", [])).strip()
            first_token = case_text.split()[0] if case_text else ""

            if CASE_TOKEN_RE.match(first_token) and re.search(r"\d", first_token):
                flush()
                accumulator = {n: [] for n, _, _ in bands}
                for k, v in by_col.items():
                    accumulator[k].extend(v)
            elif accumulator is not None:
                for k, v in by_col.items():
                    accumulator.setdefault(k, []).extend(v)

        flush()
    return rows


# ---------- Top-level ----------

def parse_document(pdf_path: Path, source_url: str) -> ParsedDoc:
    import pdfplumber

    doc = ParsedDoc(source_url=source_url, local_path=str(pdf_path), layout=LAYOUT_MID)
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return doc
        first_text = pdf.pages[0].extract_text() or ""
        doc.layout = detect_layout(first_text)
        m = REPORT_PERIOD_RE.search(first_text)
        if m:
            doc.report_period_start = m.group(1).strip()
            doc.report_period_end = m.group(2).strip()
        m2 = QUARTER_RE.search(first_text)
        if m2:
            doc.quarter = f"Q{m2.group(1)[:1]} {m2.group(2)}"

        if doc.layout in (LAYOUT_MODERN, LAYOUT_LEGACY):
            doc.rows = parse_with_extract_tables(pdf, doc.layout)
        else:
            doc.rows = parse_mid_layout(pdf)

    return doc


def main() -> int:
    if not MANIFEST_PATH.exists():
        logger.error("Manifest not found: %s", MANIFEST_PATH)
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text())
    docs: list[dict] = []
    err_log_lines: list[str] = []
    total_rows = 0

    for entry in manifest:
        local = ROOT / entry["local_path"]
        if not local.exists():
            err_log_lines.append(f"missing: {local}")
            continue
        try:
            doc = parse_document(local, entry["url"])
        except Exception as e:
            logger.exception("parse failed for %s", local)
            err_log_lines.append(f"parse_error: {local}: {e}")
            continue
        n = len(doc.rows)
        total_rows += n
        logger.info("Parsed %s -> %d rows (layout=%s)", local.name, n, doc.layout)
        docs.append(
            {
                "source_url": doc.source_url,
                "local_path": entry["local_path"],
                "layout": doc.layout,
                "report_period_start": doc.report_period_start,
                "report_period_end": doc.report_period_end,
                "quarter": doc.quarter,
                "rows": [asdict(r) for r in doc.rows],
            }
        )

    PARSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    PARSED_PATH.write_text(json.dumps(docs, indent=2))
    if err_log_lines:
        ERR_LOG.write_text("\n".join(err_log_lines))
    logger.info("Wrote %s with %d documents (%d rows total)", PARSED_PATH, len(docs), total_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
