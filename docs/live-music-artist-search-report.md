# Live Music Artist Search Quality Report

Generated on June 2, 2026 from Ticketmaster Discovery API keyword searches.

## Executive Summary

This analysis adds an artist-level view to the market data quality pipeline. I searched Ticketmaster for six artists: Sabrina Carpenter, Gracie Abrams, Taylor Swift, girl in red, Kendrick Lamar, and Bad Bunny. The goal was not only to count events, but to evaluate whether keyword-based artist search returns clean artist entities.

The main finding is that artist keyword search behaves very differently by artist. Gracie Abrams returned a clean direct-match tour sample with 33 loaded events. Taylor Swift returned 31 events, but they were mostly tribute, dance-party, or fan-event listings rather than official Taylor Swift concerts. girl in red returned noisy keyword matches such as Indigo Girls, Red Not Chili Peppers, Outside Lands, and Lily Allen. Kendrick Lamar returned zero current U.S. Ticketmaster music events in this pull.

This is a useful data-quality story: event search keywords are not the same thing as artist identity. A production pipeline should enrich Ticketmaster results with stable artist IDs, attraction IDs, or an external artist reference source before using artist-level analytics.

## Methodology

The same Ticketmaster importer was run six times using artist keywords and separate source labels:

```bash
docker compose run --rm app python -m app.ingestion.ticketmaster --keyword "Sabrina Carpenter" --country US --pages 3 --size 200 --source-name ticketmaster_artist_sabrina_carpenter --output data/raw/ticketmaster_artist_sabrina_carpenter.csv --load
docker compose run --rm app python -m app.ingestion.ticketmaster --keyword "Gracie Abrams" --country US --pages 3 --size 200 --source-name ticketmaster_artist_gracie_abrams --output data/raw/ticketmaster_artist_gracie_abrams.csv --load
docker compose run --rm app python -m app.ingestion.ticketmaster --keyword "Taylor Swift" --country US --pages 3 --size 200 --source-name ticketmaster_artist_taylor_swift --output data/raw/ticketmaster_artist_taylor_swift.csv --load
docker compose run --rm app python -m app.ingestion.ticketmaster --keyword "girl in red" --country US --pages 3 --size 200 --source-name ticketmaster_artist_girl_in_red --output data/raw/ticketmaster_artist_girl_in_red.csv --load
docker compose run --rm app python -m app.ingestion.ticketmaster --keyword "Kendrick Lamar" --country US --pages 3 --size 200 --source-name ticketmaster_artist_kendrick_lamar --output data/raw/ticketmaster_artist_kendrick_lamar.csv --load
docker compose run --rm app python -m app.ingestion.ticketmaster --keyword "Bad Bunny" --country US --pages 3 --size 200 --source-name ticketmaster_artist_bad_bunny --output data/raw/ticketmaster_artist_bad_bunny.csv --load
```

The pipeline normalized the returned events, loaded them into PostgreSQL, calculated data-quality scores, and exposed the results through `/artists/search-report` and the Streamlit dashboard.

## Artist Search Results

| Search | API Rows | Loaded Events | Unique Artists | Unique Venues | Date Range | Avg Quality Score | Issues |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| Gracie Abrams | 33 | 33 | 1 | 14 | 2026-12-02 to 2027-03-20 | 89.39 | 35 |
| Taylor Swift | 31 | 31 | 8 | 28 | 2026-06-05 to 2026-11-22 | 82.58 | 45 |
| girl in red | 5 | 5 | 4 | 4 | 2026-06-10 to 2026-09-18 | 88.00 | 7 |
| Bad Bunny | 1 | 1 | 0 | 1 | 2026-07-25 | 65.00 | 2 |
| Sabrina Carpenter | 1 | 1 | 0 | 1 | 2027-04-03 | 65.00 | 2 |
| Kendrick Lamar | 0 | 0 | 0 | 0 | None | 0.00 | 0 |

## Match Quality

Gracie Abrams was the cleanest artist pull. All 33 events mapped to Gracie Abrams as the returned artist, with 14 unique venues and a tour window from December 2026 through March 2027.

Taylor Swift showed a different kind of result. The 31 events were mostly tribute and themed events such as Taylorville, Let's Sing Taylor, Taylor Swift night parties, and other Taylor-inspired listings. This is useful for search discovery, but it is not clean enough for official artist tour analytics.

girl in red highlighted keyword ambiguity. The search returned events where the words "girl" or "red" appeared in other contexts, including Indigo Girls, Red Not Chili Peppers, Outside Lands, and Lily Allen's West End Girl event.

Sabrina Carpenter and Bad Bunny each returned one event, but both had missing artist names in the normalized attraction field. Sabrina's returned event was a Sabrina Carpenter tribute listing, and Bad Bunny's returned event was a Bad Bunny-themed dance night.

Kendrick Lamar returned zero events. The importer now handles this as a completed empty run with headers in the raw CSV, which is important because zero-result pulls should be valid data outcomes rather than pipeline failures.

## Quality Findings

| Issue Type | Count | Interpretation |
| --- | ---: | --- |
| Missing venue capacity | 71 | Ticketmaster event data still does not provide venue capacity for artist searches. |
| Invalid state | 11 | Some Ticketmaster market labels normalize awkwardly, especially multi-region market names. |
| Missing artist name | 8 | Several keyword hits did not include a clean artist attraction, especially tribute or themed events. |
| Duplicate venue candidate | 1 | One venue fingerprint appeared under multiple source IDs in the artist-search sample. |

## Recommendations

1. Use Ticketmaster attraction IDs or another artist identifier when possible instead of relying only on `keyword`.
2. Add an artist reference/enrichment table from MusicBrainz, Spotify, or a curated CSV to verify official artist identity.
3. Add a match-confidence field that compares the searched artist to the returned attraction name and event title.
4. Treat tribute events and themed dance nights as a separate event category, not as official artist concerts.
5. Keep completed zero-event runs because they are useful evidence of source coverage, not ingestion failures.

## Portfolio Takeaway

This artist-level analysis proves the pipeline can detect source-specific search quality problems, not just missing fields. It shows that a clean data product needs entity resolution, metadata enrichment, and validation rules across APIs.

Strong resume phrasing:

> Extended a live-music data quality pipeline with artist-level Ticketmaster keyword ingestion, exposing search-quality reports that identified direct artist matches, tribute-event contamination, ambiguous keyword matches, zero-result pulls, and missing artist metadata through PostgreSQL, FastAPI, and Streamlit.
