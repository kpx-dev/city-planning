.PHONY: setup scrape parse load geocode export refresh dev build deploy clean \
        scrape-santaana parse-santaana load-santaana

PYTHON := .venv/bin/python
PIP := .venv/bin/pip

setup:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	cd web && npm install

scrape:
	$(PYTHON) scripts/scrape_pdfs.py

parse:
	$(PYTHON) scripts/parse_pdfs.py

load:
	$(PYTHON) scripts/load_db.py

scrape-santaana:
	$(PYTHON) scripts/santaana_scraper.py

parse-santaana:
	$(PYTHON) scripts/santaana_parser.py

load-santaana:
	$(PYTHON) scripts/load_db_santaana.py

geocode:
	$(PYTHON) scripts/geocode.py

export:
	$(PYTHON) scripts/build_export.py

refresh: scrape parse load scrape-santaana parse-santaana load-santaana geocode export

dev:
	cd web && npm run dev

build:
	cd web && npm run build

deploy:
	git push origin main

clean:
	rm -rf web/dist
