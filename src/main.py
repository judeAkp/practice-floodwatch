"""Entry point.

    python -m src.main --day 2026-11-14
    python -m src.main --day 2026-11-13 --day 2026-11-14 --day 2026-11-15
    python -m src.main --day 2026-11-14 --offline

--offline means "do not touch the API, use the raw files already on disk".
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from config import RAW_DIR, READING_DIR, STATION_DIR
from src.extract import extract_readings, extract_stations
from src.transform import (DataQualityError, build_dim_date, build_dim_measure,
                           build_dim_station, build_fact_reading, completeness_gaps,
                           quality_checks)

LOG = logging.getLogger("floodwatch")


def write_processed_csvs(tables, day):
    """A dry run still leaves evidence: one CSV per table under data/processed."""
    from config import PROCESSED_DIR
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        path = Path(PROCESSED_DIR) / f"{name}_{day.isoformat()}.csv"
        frame.to_csv(path, index=False)
        LOG.info("wrote %s", path.name)


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler("pipeline.log", encoding="utf-8")],
    )


def load_snapshots():
    """Every station snapshot on disk, keyed by date string."""
    return {path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((Path(STATION_DIR)).glob("*.json"))}


def read_readings(day):
    """The readings file for one day, already saved by extract."""
    path = Path(READING_DIR) / f"readings_{day.isoformat()}.json"
    if not path.exists():
        raise FileNotFoundError(f"no raw readings for {day} - run without --offline")
    return json.loads(path.read_text(encoding="utf-8"))["readings"]


def run(day, offline=False, dry_run=False, today=None):
    today = today or date.today()

    if not offline:
        LOG.info("refreshing station snapshot and readings for %s", day)
        extract_stations(as_of=day)
        extract_readings(day)
    else:
        LOG.info("offline mode: using raw files already on disk")

    snapshots = load_snapshots()
    latest_snapshot = snapshots[max(snapshots)]

    dim_station = build_dim_station(snapshots)
    dim_measure = build_dim_measure(latest_snapshot)
    dim_date = build_dim_date(min(snapshots), max(day, max(date.fromisoformat(k) for k in snapshots)))
    LOG.info("dimensions: %s station versions, %s measures, %s dates",
             len(dim_station), len(dim_measure), len(dim_date))

    readings = read_readings(day)
    fact, rejections = build_fact_reading(readings, dim_measure)
    LOG.info("readings: %s raw -> %s clean, %s rejected",
             len(readings), len(fact), len(rejections))
    for rejection in rejections[:5]:
        LOG.warning("rejected: %s", rejection)

    gaps = completeness_gaps(fact, day)
    short = gaps[gaps["missing"] > 0]
    if not short.empty:
        LOG.warning("%s measures are missing readings (worst %s)",
                    len(short), int(short["missing"].max()))

    is_finished_day = day < today
    try:
        quality_checks(fact, day, is_finished_day)
    except DataQualityError as error:
        for failure in error.failures:
            LOG.error("quality check failed: %s", failure)
        LOG.error("nothing loaded for %s", day)
        return 1

    tables = {"dim_station": dim_station, "dim_measure": dim_measure,
              "dim_date": dim_date, "fact_reading": fact}

    if dry_run:
        write_processed_csvs(tables, day)
        LOG.info("dry run: everything built, nothing written to SQL Server")
        return 0

    # Imported here so that --dry-run works even on a machine without the
    # SQL Server driver installed.
    from src.load import load_all
    load_all(dim_station, dim_measure, dim_date, fact, day)
    LOG.info("done: %s", day)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Flood Watch pipeline")
    parser.add_argument("--day", action="append", required=True,
                        help="day to load, YYYY-MM-DD (repeat for several days)")
    parser.add_argument("--offline", action="store_true",
                        help="use raw files on disk instead of calling the API")
    parser.add_argument("--dry-run", action="store_true",
                        help="build everything and write CSV files, skip SQL Server")
    args = parser.parse_args()
    setup_logging()

    exit_code = 0
    for day_text in args.day:
        day = date.fromisoformat(day_text)
        try:
            exit_code = run(day, offline=args.offline, dry_run=args.dry_run) or exit_code
        except Exception:
            LOG.exception("pipeline failed for %s", day)
            exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
