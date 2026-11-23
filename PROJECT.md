# Project: Flood Watch

**Type:** practice project 2 (after the grid carbon pipeline)
**Time:** about 6 days at 1-2 hours a day
**Data:** Environment Agency flood-monitoring API, Open Government Licence v3.0
**Stack:** Python, pandas, SQL Server (`DE_Learning`), T-SQL

## The problem

The Environment Agency publishes river levels for thousands of gauging
stations, updated every 15 minutes. Nobody needs all of them. A water
resources analyst in the Midlands needs to know: *are the rivers around
Birmingham rising, which stations are reporting properly, and has any
station's description changed under us?*

Build the pipeline that answers those three questions from a database, not from
a spreadsheet.

## Questions the warehouse must answer

1. What is the newest reading for every measuring device, and when was it taken?
2. Which devices moved the most over the loaded window, and in which direction?
3. Which devices are missing readings, on which days, and how many?
4. Which stations have changed description since we started, and what changed?
5. What were the peak and lowest levels on each river - compared only within
   the same unit of measurement?
6. Is any station suspended but still reporting?
7. Why can you not average a level across units?

## Why this project is different from the Week 4 one

| Week 4 (grid carbon) | This project (flood) |
|---|---|
| One API call returns a whole month | 35 API calls return one day |
| Dimension is fixed (`dim_fuel` never changes) | Station metadata changes: **type 2 dimension** |
| Full-month load, every run | **Incremental load by day**, tracked by a watermark |
| Every measure is a percentage | Measures come in **three units that must not be mixed** |
| All devices report | **5 of 35 devices never report anything** |

## Architecture

```
EA flood-monitoring API
        |
        |  src/extract.py   (35 polite requests, retries, one file per day)
        v
data/raw/stations/YYYY-MM-DD.json     data/raw/readings/readings_YYYY-MM-DD.json
        |                                        |
        |  src/transform.py (replay snapshots -> type 2 history)
        v                                        v
  dim_station (35 rows, 31 stations)      dim_measure (35 rows)
                                   \        /
                                    fact_reading (2,880 rows a day)
        |
        |  src/load.py  (one transaction, delete-one-day-then-insert, watermark)
        v
DE_Learning : flood.* tables  ->  sql/analysis.sql  ->  answers
```

## Design decisions you must be able to defend

1. **Snapshot and replay.** The dimension is rebuilt from every snapshot on
   disk, in date order. That is a full rebuild, which makes it idempotent: run
   it twice and the history is identical.
2. **`valid_to` is the day before the next `valid_from`.** A version is true
   from `valid_from` to `valid_to` inclusive. Gaps and overlaps are both bugs.
3. **Facts join on the business key, not the version.** `fact_reading` stores
   `station_key`, and a query picks the version with `is_current = 1` (today)
   or with `BETWEEN valid_from AND valid_to` (as of the reading date).
4. **Store UTC, report local.** `reading_at_utc` is what the API gave us;
   `reading_date` is the Europe/London day, which is what the analyst means.
5. **Units are part of the measure, not the fact.** mASD, mAOD and m are
   different rulers. `dim_measure.unit_name` travels with every reading.
6. **A day is replaced, not appended.** Delete the day, insert the day, inside
   one transaction, so a re-run cannot duplicate anything.

## What is real and what is simulated

`data/raw/stations/2026-11-13.json` and all three readings files are genuine
API responses. `data/raw/stations/2026-11-14.json` and `2026-11-15.json` are
that real snapshot plus three documented edits, made by `src/make_churn.py`, so
that a type 2 dimension has something to record. The edits are: a station
suspended, a missing catchment name filled in, a station renamed, and then the
suspended station reinstated.

## Definition of done

- [ ] `python -m src.main --day 2026-11-14 --offline --dry-run` builds four tables
- [ ] `python -m src.main --day 2026-11-13 --day 2026-11-14` loads SQL Server
- [ ] Running the same day twice leaves the row count unchanged
- [ ] `sql/analysis.sql` answers all seven questions with real numbers
- [ ] `pytest -q` passes
- [ ] README explains the pipeline in under 400 words with one number per claim
- [ ] You can explain, out loud, why `is_current = 1` is wrong for Q6
