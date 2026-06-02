# Live Music Market Data Quality Report

Generated on June 2, 2026 from the Ticketmaster Discovery API.

## Executive Summary

This analysis used the pipeline to pull five real Ticketmaster music-event slices: Denver, Austin, Nashville, New York, and Los Angeles. The run loaded 2,728 live-event records into PostgreSQL, representing 1,212 unique artists and 172 unique venues.

The main story is that market coverage is strong enough for useful event analysis, but venue enrichment is the biggest quality gap. Every loaded Ticketmaster record was missing venue capacity, which makes capacity-aware reporting impossible without an additional venue enrichment source. Artist metadata quality also varied sharply by market: Austin had the cleanest sample, while Nashville and New York had the highest rate of missing artist names.

## Methodology

The same ingestion workflow was run five times with different market parameters:

```bash
docker compose run --rm app python -m app.ingestion.ticketmaster --city Denver --state CO --pages 3 --size 200 --output data/raw/ticketmaster_denver.csv --load --replace
docker compose run --rm app python -m app.ingestion.ticketmaster --city Austin --state TX --pages 3 --size 200 --output data/raw/ticketmaster_austin.csv --load
docker compose run --rm app python -m app.ingestion.ticketmaster --city Nashville --state TN --pages 3 --size 200 --output data/raw/ticketmaster_nashville.csv --load
docker compose run --rm app python -m app.ingestion.ticketmaster --city "New York" --state NY --pages 3 --size 200 --output data/raw/ticketmaster_new_york.csv --load
docker compose run --rm app python -m app.ingestion.ticketmaster --city "Los Angeles" --state CA --pages 3 --size 200 --output data/raw/ticketmaster_los_angeles.csv --load
```

Each extract was normalized through the same Pandas pipeline, loaded into PostgreSQL, validated with SQL-backed quality checks, and viewed through the Streamlit dashboard.

## Market Comparison

| Market | Events | Unique Artists | Unique Venues | Avg Quality Score | Issues per Event | Event Date Range |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Austin, TX | 328 | 279 | 25 | 89.16 | 1.06 | 2026-06-02 to 2027-05-14 |
| Los Angeles, CA | 600 | 405 | 47 | 86.98 | 1.13 | 2026-06-02 to 2026-08-25 |
| Denver, CO | 600 | 409 | 35 | 85.17 | 1.20 | 2026-06-02 to 2026-10-17 |
| Nashville, TN | 600 | 200 | 23 | 81.00 | 1.37 | 2026-06-02 to 2026-08-29 |
| New York, NY | 600 | 223 | 42 | 80.88 | 1.37 | 2026-06-01 to 2026-07-02 |

Austin had the best quality profile in this pull, with the highest average score and the fewest issues per loaded event. New York and Nashville had the lowest average scores because missing artist names were much more common in those extracts.

## Quality Findings

| Issue Type | Severity | Count | Interpretation |
| --- | --- | ---: | --- |
| Missing venue capacity | Warning | 2,728 | Ticketmaster event data does not provide venue capacity in this extract. Capacity should be enriched from a venue reference table or another source. |
| Missing artist name | Error | 632 | Some events do not include a clean music attraction/artist object. This affects artist-level deduplication and reporting. |
| Duplicate venue candidate | Warning | 21 | Multiple source venue IDs normalize to the same venue fingerprint. This is a useful signal for venue master-data cleanup. |
| Duplicate artist candidate | Warning | 6 | Multiple source artist IDs normalize to the same artist fingerprint. This is a smaller but relevant artist identity issue. |
| Invalid coordinates | Warning | 6 | A small number of venue records have missing or invalid coordinate fields. |

Missing venue capacity is the clearest enrichment opportunity. It appears in every record, so the dashboard correctly flags it as a systemic source limitation rather than a random data-entry issue.

## Market Stories

Austin looks like the cleanest market in this sample. It had fewer records because the API returned 328 events across the requested pages, but it had strong artist coverage, 279 unique artists, and the highest average quality score. Its top genres were Rock, Pop, Blues, Hip-Hop/Rap, and Other.

Los Angeles was the broadest market by venue diversity, with 47 unique venues and 405 unique artists across 600 events. The top genres were Rock, Pop, Hip-Hop/Rap, R&B, and Other, which makes it the most genre-diverse of the five samples.

Denver had strong artist diversity, with 409 unique artists across 600 events, but a lower score than Los Angeles because it had more missing artist names. Its top genres were Rock, Other, World, Dance/Electronic, and Pop.

Nashville showed the clearest market identity. Country was the top genre with 171 events, far ahead of the next genres. The data quality score was lower because 216 events were missing artist names.

New York had a distinctive Jazz concentration: Jazz was nearly tied with Rock among the top genres. It also had the lowest average quality score, mostly because 219 events were missing artist names.

## Venue Concentration

The most active venues in the pull were:

| Market | Top Venue | Events | Avg Quality Score |
| --- | --- | ---: | ---: |
| Austin, TX | Antone's Nightclub | 69 | 87.10 |
| Denver, CO | La Rumba | 79 | 65.00 |
| Los Angeles, CA | Blue Note Los Angeles | 104 | 81.35 |
| Nashville, TN | 3rd and Lindsley | 84 | 73.63 |
| New York, NY | Blue Note Jazz Club | 68 | 83.75 |

These venues are useful candidates for deeper enrichment because they drive a large share of each market's event volume. Adding verified capacity, venue type, ownership, and neighborhood metadata for these high-volume venues would improve downstream reporting quickly.

## Recommendations

1. Add a venue reference table with verified capacity, venue type, latitude/longitude, and neighborhood fields.
2. Add an artist enrichment step from MusicBrainz or another public artist metadata source to reduce missing artist-name issues.
3. Keep Ticketmaster as the event spine, but treat venue capacity as a separate master-data problem.
4. Add dashboard filters by market, genre, and quality issue so users can drill into one market at a time.
5. Track data quality over time by preserving daily ingestion runs instead of replacing the database for every demo pull.

## Portfolio Takeaway

This project now demonstrates more than ingestion. It shows a repeatable data-quality workflow across five live-music markets, surfaces source-specific quality gaps, and translates raw API data into business-facing monitoring. The strongest resume story is:

> Built a live-music data quality pipeline that ingested 2,728 real Ticketmaster event records across five U.S. markets, normalized artist/venue/market fields, loaded the results into PostgreSQL, and surfaced missing venue capacity, missing artist metadata, duplicate candidates, and market-level genre trends through SQL views and a Streamlit dashboard.
