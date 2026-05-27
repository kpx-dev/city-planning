# City Planning Explorer

Open-data map and table for civic development projects, starting with the
City of **Garden Grove, CA**. The pipeline scrapes the city's quarterly
*Development Projects Update List* (DPU) PDFs going back ~10 years, parses
them into structured rows, geocodes the addresses, and serves the result as
a static React/MapLibre web app on GitHub Pages.

**Live site:** https://kpx-dev.github.io/city-planning/

![map screenshot placeholder](docs/screenshot.png)

## What it does

- Discovers historical DPU PDFs (2014 – present) by walking the Wayback Machine
  CDX index of `ggcity.org`. Falls back to live URLs first, then Wayback `id_/`
  bytes when the city's site is offline.
- Parses three distinct table layouts (border-table 2014–16, position-based
  2017–18, modern table 2019+) using `pdfplumber`/`pymupdf`.
- Loads parsed rows into SQLite (`data/city-planning.sqlite`), de-duped by
  `(city, case_number, address)` so the same project across multiple quarterly
  reports collapses to one record with merged history.
- Geocodes unique addresses through Nominatim (1 req/sec, cached, with sanity
  bounds-check so out-of-area matches like "Garden Grove Boulevard, Ohio" are
  rejected).
- Exports `web/public/data/{projects,meta}.json` consumed by the React app.

## Pipeline

```bash
make setup       # one-time: venv, pip install, npm install
make scrape      # discover + cache all DPU PDFs into data/raw/
make parse       # parse PDFs into data/parsed.json
make load        # load into data/city-planning.sqlite
make geocode     # geocode addresses (slow: 1 req/sec)
make export      # emit web/public/data/{projects,meta}.json
make refresh     # all of the above end-to-end
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
insert a row in `cities`, add a scraper that drops PDFs into `data/raw/`, and
update `parse_pdfs.py` to recognize that city's layout.

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

Data comes from public records published by the City of Garden Grove. Map
tiles © OpenStreetMap contributors. Historical PDFs sourced via the Internet
Archive's Wayback Machine.

## License

MIT — see [LICENSE](LICENSE).
