# Flood Watch

An offline-capable data pipeline that turns Environment Agency river readings
and station snapshots into a queryable SQL Server warehouse.

## What it does

1. Snapshots station metadata around Birmingham (31 stations, 35 measuring devices).
2. Downloads one day of 15-minute readings per device, politely and with retries.
3. Builds a **type 2 station dimension** by replaying every snapshot in date order.
4. Loads `fact_reading` for one day, replacing that day if it is re-run.
5. Answers eight analytical questions, including a type-2 "as of" query, in
   `sql/analysis.sql`.

## Findings

- Five of the 35 measuring devices had no readings on each loaded day, so 30
  devices contributed readings (Q3).
- The River Tame's highest loaded mASD reading was 1.481 m (Q5).
- Station 2538 had two versions after its label changed on 15 November; the
  complete dimension contains 33 versions for 31 stations (Q4).
- No station version is marked Suspended in the current snapshots, so the
  date-aware query returns no rows (Q6).

## How to run

```bash
pip install -r requirements.txt
python -m src.main --day 2026-11-13 --day 2026-11-14 --day 2026-11-15 --offline --dry-run
python -m src.main --day 2026-11-14
python -m pytest -q
```

`--offline` uses the raw files already in `data/raw/`. Drop it to call the live API.
The loader replaces only the requested day's readings; rerunning a day does not
duplicate its fact rows. Its schema setup is safe to rerun and does not drop
existing warehouse data.

## Design notes

- Replaying snapshots in date order makes the station history deterministic
  and repeatable instead of relying on fragile incremental patches.
- Readings retain both the measure and station surrogate keys, plus the UTC
  timestamp and London-local business date used for daily analysis.
- A version's inclusive `valid_to` ends the day before the next version starts;
  the current version uses `9999-12-31`.

## Attribution

Contains Environment Agency flood-monitoring data, licensed under the Open
Government Licence v3.0.
