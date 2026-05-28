# City Planning Explorer

Open-data map and table for civic development projects across multiple
cities. The pipeline scrapes each city's published development project
records, parses them into structured rows, geocodes the addresses, and
serves the result as a static React/MapLibre web app on GitHub Pages.

**Live site:** https://kpx-dev.github.io/city-planning/

### Cities covered

| City | Source | Coverage | Projects |
|------|--------|----------|----------|
| Garden Grove, CA | Quarterly DPU PDFs | 2014 – Q1 2026 | 856 |
| Santa Ana, CA    | Major Projects HTML + monthly PDFs | 2022 – Q1 2026 | 154 |

![map screenshot placeholder](docs/screenshot.png)

## What it does

- **Garden Grove**: walks the Wayback Machine CDX index of `ggcity.org` to
  discover historical *Development Projects Update List* PDFs going back ~10
  years. Three distinct table layouts (border-table 2014–16, position-based
  2017–18, modern table 2019+) parsed with `pdfplumber`/`pymupdf`.
- **Santa Ana**: scrapes the Major Planning Projects HTML table plus ~45
  monthly Accepted Development Projects PDFs from
  `storage.googleapis.com/proudcity/santaanaca/...`. Wraps the rows into the
  same schema.
- Loads parsed rows into SQLite (`data/city-planning.sqlite`), de-duped per
  city by `(city, case_number, address)` so the same project across multiple
  reports collapses to one record with merged history.
- Geocodes unique addresses through Nominatim (1 req/sec, cached, with
  per-city sanity bounds so out-of-area matches like "Garden Grove Boulevard,
  Ohio" are rejected).
- Exports `web/public/data/{projects,meta}.json` consumed by the React app.

## Pipeline

```bash
make setup            # one-time: venv, pip install, npm install
make scrape           # download all Garden Grove DPU PDFs
make parse            # parse Garden Grove PDFs -> data/parsed.json
make load             # load Garden Grove into data/city-planning.sqlite
make scrape-santaana  # download Santa Ana sources (HTML + monthly PDFs)
make parse-santaana   # parse Santa Ana -> data/parsed_santaana.json
make load-santaana    # load Santa Ana into the same SQLite DB
make geocode          # geocode all unmapped addresses (slow: 1 req/sec)
make export           # emit web/public/data/{projects,meta}.json
make refresh          # everything end-to-end (Garden Grove + Santa Ana)
```

`make dev` serves the web app locally; `make build` produces a production
bundle.

## Schema (multi-city ready)

```
cities    (id, name, state, slug)
sources   (id, city_id, url, title, period_start, period_end, published_date,
           fetched_at, sha256)
projects  (id, city_id, case_number, address, description, applicant_*,
           planner_initials, district, hearing_body, status, section,
           latitude, longitude, first/last_seen_*)
geocode_cache (raw_address, query, latitude, longitude, ...)
```

`projects` has `UNIQUE(city_id, case_number, address)`. To add another city,
insert a row in `cities`, add a scraper for that city's source, write a parser
that emits the same row shape, and add a per-city loader. Santa Ana support
(`scripts/santaana_scraper.py`, `santaana_parser.py`, `load_db_santaana.py`)
is the reference for how multi-city extension looks.

## Deploy

GitHub Actions builds the Vite app with `BASE_PATH=/city-planning/` and
publishes `web/dist/` via `actions/deploy-pages`. The data pipeline does **not**
run in CI — `data/city-planning.sqlite` and `web/public/data/*.json` are
committed to the repo so Pages just serves static files. Refresh data locally
with `make refresh` and commit.

## Stack

- **Pipeline:** Python 3, `pdfplumber`, `pymupdf`, `requests`, SQLite,
  Nominatim/OSM
- **Web:** Vite, React, TypeScript, Tailwind, MapLibre GL JS, supercluster
- **Hosting:** GitHub Pages via Actions

## Credits

Data comes from public records published by the City of Garden Grove
(quarterly DPU reports) and the City of Santa Ana (major projects table and
monthly accepted-projects reports). Map tiles © OpenStreetMap contributors.
Historical Garden Grove PDFs sourced via the Internet Archive's Wayback
Machine.

## License

MIT — see [LICENSE](LICENSE).
