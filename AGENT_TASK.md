# Task: Garden Grove City Planning Project Map

You are building a beautiful, deployable web app that visualizes City of Garden Grove (CA) development project data on a map, with a SQLite-backed pipeline that scrapes and parses the city's published "Development Projects Update List" PDFs going back ~10 years (2015–2026). Architecture must support adding more cities/states later.

Working directory: `/Users/kien/kp/city-planning` (already a git repo, branch `main`, remote `origin` = `git@github.com:kpx-dev/city-planning.git`, currently PRIVATE on GitHub).

## Owner / Context
- Owner: Kien (kpx-dev on GitHub, kien@kienpham.com)
- Use `gh` CLI; SSH auth already configured.
- Default model preference for generated code: keep it simple, modern, no over-engineering.
- Use `~/.openclaw/workspace` only if you need to read shared notes; otherwise stay in `/Users/kien/kp/city-planning`.

## Deliverables

1. **Data pipeline (Python preferred for PDF parsing)**
   - `scripts/scrape_pdfs.py` — discover and download all Garden Grove DPU PDFs from ggcity.org going back ~10 years. Sources include:
     - Quarterly DPU PDFs at `https://ggcity.org/sites/default/files/...pdf` with names like `dpu*.pdf`, `qN-*.pdf`, `final-list.pdf`, `q3-final-draft.pdf`, `q4-final.pdf`, `q1-2026-finalver2.pdf`, etc.
     - Embedded as attachments in `wm<MMDDYY>.pdf` City Manager weekly memos.
     - Landing page: `https://ggcity.org/planning/development-projects-update-list`
     - Older `www/commdev/dpu*.pdf` and `www/planning/dpu*.pdf` paths (e.g. `dpu101314.pdf`, `dpu2014-march2016.pdf`).
   - Strategy: crawl ggcity.org for any PDF whose first page contains the phrase "DEVELOPMENT PROJECTS UPDATE LIST" (case-insensitive). Cache PDFs under `data/raw/<source-slug>.pdf`. Be polite (small concurrency, cache, skip already-downloaded).
   - `scripts/parse_pdfs.py` — extract structured rows. Use `pdfplumber` or `pymupdf` (fitz). The PDFs use a tabular layout with columns: `Case #`, `Project Addresses`, `Project Description`, `Applicant` (name + address possibly multi-line), `Planner` (initials), `Districts`, `Hearing Body`. Handle merged cells, wrapped text, multi-line cells. Also try to parse phone numbers and emails out of the Applicant block when present. Capture report period (e.g. "January 2024 through December 2025") and publication date from each PDF.
   - `scripts/load_db.py` — load parsed rows into SQLite at `data/city-planning.sqlite`. Schema (multi-city ready):

     ```sql
     CREATE TABLE cities (
       id INTEGER PRIMARY KEY,
       name TEXT NOT NULL,
       state TEXT NOT NULL,
       slug TEXT UNIQUE NOT NULL
     );
     CREATE TABLE sources (
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
     CREATE TABLE projects (
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
       status TEXT,                  -- "in_process" | "approved" | "withdrawn" | "completed" | "unknown"
       section TEXT,                 -- raw section header in PDF (e.g. "IN PROCESS IN PLANNING DIVISION")
       latitude REAL,
       longitude REAL,
       first_seen_source_id INTEGER REFERENCES sources(id),
       last_seen_source_id INTEGER REFERENCES sources(id),
       first_seen_date TEXT,
       last_seen_date TEXT,
       UNIQUE(city_id, case_number, address)
     );
     CREATE INDEX idx_projects_city ON projects(city_id);
     CREATE INDEX idx_projects_case ON projects(case_number);
     ```

     Dedupe by `(city_id, case_number)` when present, else by `(city_id, normalized_address, description hash)`. When the same case appears in multiple sources, keep the latest description/status and update `last_seen_*`.

   - `scripts/geocode.py` — geocode each unique address to lat/lon. Use the free Nominatim (OpenStreetMap) API with a custom User-Agent and 1 req/sec rate limit. Cache results in a `geocode_cache` table keyed by raw address. Skip empties. For Garden Grove, append ", Garden Grove, CA" if not present.
   - `scripts/build_export.py` — emit `web/public/data/projects.json` (array of project rows with lat/lon and key fields) and `web/public/data/meta.json` (city list, last update timestamp, counts). Keep payload < 5 MB; truncate descriptions if needed but keep full text in SQLite.

2. **Web app (in `web/`)**
   - Stack: **Vite + React + TypeScript + Tailwind CSS + MapLibre GL JS** (no Mapbox token needed — use the free OpenFreeMap or MapTiler basic style, or fall back to a raster OSM style). MapLibre is preferred over Leaflet for the visual polish.
   - Pages/views:
     - **Map view (default)**: full-screen map centered on Garden Grove (33.7739, -117.9414). Project markers clustered with `supercluster`. Click a marker → side panel with project details (case #, address, description, applicant, status, hearing body, source link to original PDF).
     - **List/table view**: sortable/filterable table of all projects. Filters: city, status, hearing body, year, search by case # / address / description.
     - **Project detail page**: deep-link `/p/:caseNumber`.
   - UI: modern, clean, dark-mode toggle. Use shadcn/ui (or hand-rolled Tailwind components) for the side panel, filters, and table. Subtle animations.
   - Data loading: fetch the static JSON files from `./data/projects.json` (relative path so it works under GitHub Pages subpath).
   - Multi-city scaffolding: a `CitySelector` in the header, even if only Garden Grove is present.
   - Header: "City Planning Explorer" + small subtitle "Open data for civic projects". Footer credits OpenStreetMap and the City of Garden Grove.

3. **GitHub Pages deploy**
   - Add `.github/workflows/deploy.yml` that on push to `main` (or manual dispatch):
     1. Sets up Python (for the data pipeline) — but only if `data/city-planning.sqlite` is missing (data is committed).
     2. Sets up Node 22, builds Vite app with `--base=/city-planning/`.
     3. Publishes `web/dist/` to GitHub Pages via `actions/deploy-pages`.
   - The data pipeline must NOT run in CI by default — commit the SQLite db and JSON exports so Pages just serves static files. Provide a `make refresh` (or `npm run refresh`) that re-runs the pipeline locally.
   - Make the repo public (Pages on private requires Pro). Run `gh repo edit kpx-dev/city-planning --visibility public --accept-visibility-change-consequences`. Confirm with the user via the AGENT_TASK.md NOTES section if you'd rather skip — but default is "make public" since they explicitly asked for Pages preview.
   - Enable Pages: `gh api -X POST repos/kpx-dev/city-planning/pages -f build_type=workflow` (or via the workflow). Source = GitHub Actions.

4. **Polish**
   - `README.md`: project overview, screenshot placeholder, how to run pipeline, how the schema scales to other cities, link to live site.
   - `.gitignore`: standard Node + Python + macOS.
   - `LICENSE` already present (don't touch).
   - `Makefile` with: `setup`, `scrape`, `parse`, `load`, `geocode`, `export`, `refresh` (= scrape→parse→load→geocode→export), `dev`, `build`, `deploy`.

## Execution Order
1. Set up repo skeleton: `web/` (Vite scaffold), `scripts/`, `data/raw/`, `data/`, `.github/workflows/`, `Makefile`, `README.md`, `.gitignore`, `pyproject.toml` or `requirements.txt`.
2. Implement scrape → parse → load against a small seed (start with: `q1-2026-finalver2.pdf`, `q4-final.pdf`, `q3-final-draft.pdf`, `final-list.pdf`, `dpu101314.pdf`, `dpu2014-march2016.pdf`). Verify a handful of rows look right.
3. Expand crawl to find all historical DPU PDFs going back to ~2015. Persist results.
4. Geocode (rate-limited).
5. Export JSON, build web app pointing at it.
6. Deploy to Pages, verify the URL responds.
7. Commit and push everything in logical commits.

## Don't
- Don't commit raw PDFs to git unless small (< 1 MB each — they probably are). If commit, fine; otherwise gitignore `data/raw/` and rely on `make refresh` locally.
- Don't depend on Mapbox/paid APIs.
- Don't pollute the repo with node_modules or `.venv`.
- Don't break the existing `LICENSE` file.

## Verification Checklist (must pass before declaring done)
- [ ] `data/city-planning.sqlite` exists and has > 50 Garden Grove projects.
- [ ] `web/public/data/projects.json` validates as JSON, > 50 entries, ≥ 60% have lat/lon.
- [ ] `npm run build` (in `web/`) succeeds with no type errors.
- [ ] `npm run dev` shows the map with markers and a side panel that opens on click.
- [ ] `gh run list --workflow=deploy.yml` shows a successful run.
- [ ] Live URL `https://kpx-dev.github.io/city-planning/` returns 200 and renders the map (curl + visual confirmation if possible).
- [ ] README updated with the live URL.
- [ ] All work committed and pushed to `origin/main`.

## NOTES (back-channel to the spawning agent)

**Status: DONE.** Live at https://kpx-dev.github.io/city-planning/

### Final stats
- **31** historical DPU PDFs cached (2014 -> Q1 2026)
- **744** raw rows parsed across three layout generations
- **486** unique projects after dedup `(city, case_number, address)`
- **418 / 486 = 86.0%** geocoded (well above the 60% bar)
- Build: 1.0 MB JS bundle (gzipped 280 KB), 80 KB CSS
- `data/city-planning.sqlite` is **528 KB** -- committed to git
- `web/public/data/projects.json` is **0.56 MB** -- committed
- GitHub Actions deploy runs **35-60s** end-to-end

### Gotchas / things future-me should know

1. **ggcity.org was offline** during this session -- direct curls all timed
   out with ECONNREFUSED. The scraper falls back to Wayback Machine `id_/`
   URLs (raw original bytes). Discovery uses the CDX API on prefix patterns.
   When the site comes back, the scraper prefers live URLs first.

2. **Three PDF layouts**, detected by `detect_layout()` from first-page text:
   - **modern** (2019+): visible borders -> `pdfplumber.extract_tables()`
   - **legacy** (2014-16): visible borders -> same path
   - **mid** (2017-18): no borders -> position-based via x-coordinate bands
     extracted from header words. Header detection combines adjacent y-lines
     within 12pt because old PDFs split "SITE ADDRESS / AND LOCATION" across
     three baselines.

3. **Geocoder false positives**: Nominatim happily returns "Garden Grove
   Boulevard, Columbus, OH" for some addresses without a clear locality.
   Sanity bounds-check (33.5-34.1 N, -118.3 to -117.5 W) rejects these and
   marks them as `out_of_area` in `geocode_cache`. Misses logged to
   `data/geocode_misses.log`.

4. **Status normalization**: 2017-18 PDFs use a numeric legend (1-9) at the
   bottom; this is mapped via `STATUS_LEGEND_MID`. Modern PDFs use section
   headers like "IN PROCESS IN PLANNING DIVISION" -- these populate `section`
   and the normalizer infers status from keywords.

5. **Repo was made public** via `gh repo edit --visibility public` (Pages on
   private requires Pro). User explicitly authorized this in spec.

6. **CI does not run the pipeline.** The DB and JSON exports are committed,
   so the workflow only does `npm ci && npm run build` + `deploy-pages`.
   Refresh data locally with `make refresh`.

7. Raw PDFs (`data/raw/*.pdf`) are gitignored. `manifest.json` is committed
   so the next agent can reproduce downloads.

### Manual steps still required
None. The site is live, the workflow auto-deploys on push to `main`.

### If something breaks
- Re-run the pipeline: `make refresh`
- If ggcity.org is back up, the scraper will pull fresh PDFs automatically
- New quarterly DPU? Add the URL to `EXTRA_URLS` in `scripts/scrape_pdfs.py`
  if it's not yet on Wayback.
