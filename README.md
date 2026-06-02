# Live Music Data Quality Pipeline

A portfolio-ready data engineering project that ingests messy live-music event, venue, artist, and market data; normalizes it with Python and Pandas; validates quality rules; loads clean records into PostgreSQL; and exposes monitoring through a FastAPI API and Streamlit dashboard.

The project is built to demonstrate the work behind this resume claim:

> Built a live-music data quality pipeline using Python, Pandas, PostgreSQL, FastAPI, Docker, and AWS deployment patterns to ingest, clean, validate, and monitor 100k+ artist, venue, and event records from API/CSV sources.

## Featured Analysis

The pipeline has also been run against a five-market Ticketmaster sample covering Denver, Austin, Nashville, New York, and Los Angeles. See [docs/live-music-market-quality-report.md](docs/live-music-market-quality-report.md) for the portfolio-ready report, including market comparisons, data-quality findings, venue concentration, genre trends, and recommendations.

It also supports artist-level Ticketmaster keyword pulls. See [docs/live-music-artist-search-report.md](docs/live-music-artist-search-report.md) for an artist-search quality analysis covering Sabrina Carpenter, Gracie Abrams, Taylor Swift, girl in red, Kendrick Lamar, and Bad Bunny.

## Architecture

```mermaid
flowchart LR
    A["CSV/API-style raw event data"] --> B["Pandas ingestion pipeline"]
    B --> C["Normalization and validation"]
    C --> D["PostgreSQL clean event table"]
    C --> E["PostgreSQL data quality issue table"]
    D --> F["SQL quality views"]
    E --> F
    F --> G["FastAPI API endpoints"]
    F --> H["Streamlit dashboard"]
```

## What It Checks

- Messy artist, venue, city, state, market, genre, and date values
- Missing venue capacity
- Malformed event dates
- Duplicate artist and venue candidates
- Invalid or missing coordinates
- Inconsistent source quality by provider
- Top markets by live-event volume

## Tech Stack

- Python 3.9+ locally, Python 3.11 in Docker
- Pandas
- PostgreSQL
- SQLAlchemy and psycopg
- FastAPI
- Streamlit
- Docker and Docker Compose
- GitHub Actions
- AWS RDS/EC2 deployment guide

## Quickstart With Docker

Start PostgreSQL, the FastAPI app, and the Streamlit dashboard:

```bash
docker compose up --build
```

In another terminal, generate 100k mock records and ingest them:

```bash
docker compose run --rm app python -m app.ingestion.generate_mock_data --rows 100000 --output data/raw/mock_events.csv
docker compose run --rm app python -m app.ingestion.pipeline --input data/raw/mock_events.csv --replace
```

Or pull real music events from Ticketmaster after adding `TICKETMASTER_API_KEY` to a local `.env` file:

```bash
docker compose run --rm app python -m app.ingestion.ticketmaster --city Denver --state CO --pages 2 --output data/raw/ticketmaster_denver.csv --load --replace
```

Pull artist-level Ticketmaster keyword results:

```bash
docker compose run --rm app python -m app.ingestion.ticketmaster --keyword "Gracie Abrams" --country US --pages 3 --size 200 --source-name ticketmaster_artist_gracie_abrams --output data/raw/ticketmaster_artist_gracie_abrams.csv --load
```

Open the dashboard and API:

- Dashboard: http://localhost:8501
- Health: http://localhost:8000/health
- Data quality report: http://localhost:8000/data-quality-report
- Venue issues: http://localhost:8000/venues/issues
- Artist duplicates: http://localhost:8000/artists/duplicates
- Artist search report: http://localhost:8000/artists/search-report
- Top markets: http://localhost:8000/markets/top
- Interactive docs: http://localhost:8000/docs

## Local Python Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run Postgres with Docker:

```bash
docker compose up db
```

Generate and ingest data:

```bash
python -m app.ingestion.generate_mock_data --rows 100000 --output data/raw/mock_events.csv
python -m app.ingestion.pipeline --input data/raw/mock_events.csv --replace
```

Start FastAPI:

```bash
uvicorn app.main:app --reload
```

Start the Streamlit dashboard:

```bash
streamlit run app/dashboard.py
```

Run tests:

```bash
pytest
```

## Ingestion Commands

Use the included small fixture:

```bash
python -m app.ingestion.pipeline --input data/raw/sample_events.csv --replace
```

Generate a larger file:

```bash
python -m app.ingestion.generate_mock_data --rows 250000 --output data/raw/mock_events.csv
```

Ingest in chunks:

```bash
python -m app.ingestion.pipeline --input data/raw/mock_events.csv --chunk-size 10000 --replace
```

Fetch real Ticketmaster music events to CSV:

```bash
TICKETMASTER_API_KEY=your-key \
python -m app.ingestion.ticketmaster --city Denver --state CO --pages 2 --output data/raw/ticketmaster_denver.csv
```

Fetch and load directly into PostgreSQL:

```bash
TICKETMASTER_API_KEY=your-key \
python -m app.ingestion.ticketmaster --city Denver --state CO --pages 2 --output data/raw/ticketmaster_denver.csv --load --replace
```

Set a custom database:

```bash
DATABASE_URL=postgresql+psycopg://user:password@host:5432/live_music \
python -m app.ingestion.pipeline --input data/raw/mock_events.csv --replace
```

## SQL Views

The pipeline creates these PostgreSQL views:

- `vw_top_markets_by_event_count`
- `vw_venues_missing_metadata`
- `vw_duplicate_artist_candidates`
- `vw_duplicate_venue_candidates`
- `vw_data_quality_score_by_source`

They are designed to support API responses, dashboard cards, and ad hoc SQL analysis.

## API Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Confirms API and database reachability |
| `GET /data-quality-report` | Source-level quality scores, top issue types, and recent ingestion runs |
| `GET /venues/issues` | Venues with missing capacity or coordinate problems |
| `GET /artists/duplicates` | Artist records that appear duplicated after normalization |
| `GET /markets/top` | Top markets by event count |

## AWS Deployment

See [docs/aws-deployment.md](docs/aws-deployment.md) for an RDS and EC2 deployment path. The short version:

1. Create a PostgreSQL RDS instance.
2. Point `DATABASE_URL` at the RDS endpoint.
3. Run the ingestion job from your laptop, EC2, or CI.
4. Deploy FastAPI on EC2 with Docker Compose or systemd.
5. Restrict security groups so only the API host can reach RDS.

## Resume Bullets

- Built a live-music data quality pipeline using Python, Pandas, PostgreSQL, FastAPI, and Docker to ingest, clean, validate, and monitor 100k+ artist, venue, and event records from CSV/API-style sources.
- Implemented SQL validation checks, duplicate detection, schema constraints, and data-quality reports to flag missing venue metadata, malformed dates, inconsistent market names, invalid coordinates, and duplicate artist records.
- Designed AWS RDS/EC2 deployment documentation for a FastAPI service backed by PostgreSQL, exposing data-health endpoints for ingestion status, database integrity, and cleanup workflows.
