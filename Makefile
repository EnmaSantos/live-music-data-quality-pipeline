PYTHON ?= python3
DATA_FILE ?= data/raw/mock_events.csv
ROWS ?= 100000

.PHONY: install test lint generate-data ingest api docker-up docker-ingest

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

generate-data:
	$(PYTHON) -m app.ingestion.generate_mock_data --rows $(ROWS) --output $(DATA_FILE)

ingest:
	$(PYTHON) -m app.ingestion.pipeline --input $(DATA_FILE) --replace

api:
	uvicorn app.main:app --reload

docker-up:
	docker compose up --build

docker-ingest:
	docker compose run --rm app python -m app.ingestion.generate_mock_data --rows $(ROWS) --output $(DATA_FILE)
	docker compose run --rm app python -m app.ingestion.pipeline --input $(DATA_FILE) --replace
