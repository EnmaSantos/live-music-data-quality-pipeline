# AWS RDS and EC2 Deployment Guide

This project can run locally with Docker Compose, but the same shape maps cleanly to AWS:

- PostgreSQL on Amazon RDS
- FastAPI on EC2
- CSV/API ingestion from your laptop, EC2, or GitHub Actions

## 1. Create PostgreSQL on RDS

1. Create a PostgreSQL RDS instance.
2. Use a private subnet when possible.
3. Create a database named `live_music`.
4. Create an app user with a strong password.
5. Allow inbound PostgreSQL traffic only from the EC2 security group or your temporary IP while testing.

Example connection string:

```bash
DATABASE_URL=postgresql+psycopg://live_music_user:strong-password@your-rds-endpoint.amazonaws.com:5432/live_music
```

Run migrations and ingest data:

```bash
export DATABASE_URL=postgresql+psycopg://live_music_user:strong-password@your-rds-endpoint.amazonaws.com:5432/live_music
python -m app.ingestion.generate_mock_data --rows 100000 --output data/raw/mock_events.csv
python -m app.ingestion.pipeline --input data/raw/mock_events.csv --replace
```

## 2. Deploy FastAPI on EC2 With Docker Compose

Install Docker on the EC2 host, clone the repository, and create a `.env` file:

```bash
DATABASE_URL=postgresql+psycopg://live_music_user:strong-password@your-rds-endpoint.amazonaws.com:5432/live_music
```

Create a production compose file:

```yaml
services:
  app:
    build: .
    environment:
      DATABASE_URL: ${DATABASE_URL}
    ports:
      - "80:8000"
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Start the API:

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

Then verify:

```bash
curl http://your-ec2-public-dns/health
curl http://your-ec2-public-dns/data-quality-report
```

## 3. Security Checklist

- Store `DATABASE_URL` in EC2 environment variables, AWS Systems Manager Parameter Store, or Secrets Manager.
- Do not expose RDS publicly for a real deployment.
- Use EC2 security groups so only the API host can connect to RDS.
- Put HTTPS in front of EC2 with an Application Load Balancer or Nginx plus a certificate.
- Add automated backups on the RDS instance.

## 4. Optional GitHub Actions Ingestion

The included CI workflow runs tests. For scheduled ingestion, add a separate workflow that:

1. Checks out the repo.
2. Installs Python dependencies.
3. Reads `DATABASE_URL` from GitHub Actions secrets.
4. Runs the generator or an API pull script.
5. Runs `python -m app.ingestion.pipeline --input ...`.

For a production data source, replace the mock generator with a Ticketmaster, MusicBrainz, or Spotify extraction script that writes the same CSV columns used by the pipeline.
