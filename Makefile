PYTHON ?= python3
.PHONY: install test lint api app worker docker-up

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

api:
	uvicorn app.main:app --reload

app:
	streamlit run app/dashboard.py

worker:
	$(PYTHON) -m app.worker

docker-up:
	docker compose up --build
