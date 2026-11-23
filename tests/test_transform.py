"""Tests for the parts of the pipeline that do not need a database.

Run with:  python -m pytest -q
"""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from config import READING_DIR, STATION_DIR
from src.transform import (DataQualityError, build_dim_date, build_dim_measure,
                           build_dim_station, build_fact_reading, local_day,
                           quality_checks, station_hash, station_rows)


def load_snapshots():
    return {path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(Path(STATION_DIR).glob("*.json"))}


def load_readings(day):
    return json.loads((Path(READING_DIR) / f"readings_{day}.json")
                      .read_text(encoding="utf-8"))["readings"]


@pytest.fixture(scope="module")
def snapshots():
    return load_snapshots()


@pytest.fixture(scope="module")
def dim_measure(snapshots):
    return build_dim_measure(snapshots["2026-11-13"])


# --- station cleaning ------------------------------------------------------
def test_missing_status_becomes_none_instead_of_crashing(snapshots):
    rows = station_rows(snapshots["2026-11-13"])
    homeless = [r for r in rows if r["station_status"] is None]
    assert len(homeless) == 10          # ten stations publish no status at all


def test_status_uri_is_shortened(snapshots):
    rows = {r["notation"]: r for r in station_rows(snapshots["2026-11-13"])}
    assert rows["4172"]["station_status"] == "Active"


def test_hash_ignores_position_but_not_content(snapshots):
    rows = station_rows(snapshots["2026-11-13"])
    first, second = rows[0], dict(rows[0])
    assert station_hash(first) == station_hash(second)
    second["label"] = "Somewhere else entirely"
    assert station_hash(first) != station_hash(second)


# --- the type-2 dimension --------------------------------------------------
def test_stations_that_never_change_get_one_version(snapshots):
    dim = build_dim_station(snapshots)
    counts = dim.groupby("notation").size()
    assert counts["2539"] == 1


def test_status_changes_create_three_versions():
    active = "http://environment.data.gov.uk/flood-monitoring/def/core/statusActive"
    suspended = "http://environment.data.gov.uk/flood-monitoring/def/core/statusSuspended"
    snapshots = {
        "2026-11-13": {"items": [{"notation": "TEST", "label": "Test station",
                                  "status": active}]},
        "2026-11-14": {"items": [{"notation": "TEST", "label": "Test station",
                                  "status": suspended}]},
        "2026-11-15": {"items": [{"notation": "TEST", "label": "Test station",
                                  "status": active}]},
    }
    dim = build_dim_station(snapshots)
    versions = dim[dim["notation"] == "TEST"].sort_values("valid_from")
    assert len(versions) == 3
    assert list(versions["station_status"]) == ["Active", "Suspended", "Active"]
    assert versions["is_current"].tolist() == [0, 0, 1]


def test_closed_version_ends_the_day_before_the_next_starts(snapshots):
    dim = build_dim_station(snapshots)
    versions = dim[dim["notation"] == "2538"].sort_values("valid_from")
    assert versions["valid_to"].iloc[0] == date(2026, 11, 14)
    assert versions["valid_from"].iloc[1] == date(2026, 11, 15)


def test_rebuilding_twice_gives_the_same_history(snapshots):
    first = build_dim_station(snapshots)
    second = build_dim_station(load_snapshots())
    pd.testing.assert_frame_equal(first, second.reset_index(drop=True))


def test_snapshot_dates_may_arrive_as_strings_or_dates(snapshots):
    as_strings = build_dim_station({k: v for k, v in snapshots.items()})
    as_dates = build_dim_station({date.fromisoformat(k): v for k, v in snapshots.items()})
    pd.testing.assert_frame_equal(as_strings, as_dates)


# --- measures and dates ----------------------------------------------------
def test_measure_keys_are_deterministic_and_unique(dim_measure):
    assert dim_measure["measure_key"].is_unique
    assert dim_measure["measure_key"].tolist() == list(range(1, len(dim_measure) + 1))


def test_one_station_can_have_several_measures(dim_measure):
    per_station = dim_measure.groupby("station_notation").size()
    assert per_station.max() >= 2


def test_dim_date_marks_the_weekend(dim_date=None):
    dim = build_dim_date(date(2026, 11, 13), date(2026, 11, 15))
    assert len(dim) == 3
    assert dim["is_weekend"].tolist() == [0, 1, 1]      # Fri, Sat, Sun


# --- readings --------------------------------------------------------------
def test_timestamps_are_stored_in_utc_and_dated_locally():
    assert local_day("2026-11-14T00:00:00Z") == date(2026, 11, 14)


def test_null_and_out_of_range_values_are_rejected(dim_measure):
    readings = [
        {"measure_id": dim_measure["measure_id"].iloc[0],
         "dateTime": "2026-11-14T10:00:00Z", "value": None},
        {"measure_id": dim_measure["measure_id"].iloc[0],
         "dateTime": "2026-11-14T10:15:00Z", "value": 9999},
        {"measure_id": "not-a-real-measure",
         "dateTime": "2026-11-14T10:30:00Z", "value": 0.5},
        {"measure_id": dim_measure["measure_id"].iloc[0],
         "dateTime": "2026-11-14T10:45:00Z", "value": 0.42},
    ]
    fact, rejections = build_fact_reading(readings, dim_measure)
    assert len(fact) == 1
    assert len(rejections) == 3


def test_duplicate_readings_collapse_to_the_last_one(dim_measure):
    measure_id = dim_measure["measure_id"].iloc[0]
    readings = [
        {"measure_id": measure_id, "dateTime": "2026-11-14T10:00:00Z", "value": 1.0},
        {"measure_id": measure_id, "dateTime": "2026-11-14T10:00:00Z", "value": 2.0},
    ]
    fact, _ = build_fact_reading(readings, dim_measure)
    assert len(fact) == 1
    assert fact["value"].iloc[0] == 2.0


def test_a_real_day_of_readings_passes_the_quality_gate(dim_measure):
    fact, _ = build_fact_reading(load_readings("2026-11-14"), dim_measure)
    quality_checks(fact, date(2026, 11, 14), is_finished_day=True)   # must not raise
    assert len(fact) == 2880


def test_an_empty_fact_is_refused(dim_measure):
    with pytest.raises(DataQualityError):
        quality_checks(pd.DataFrame(), date(2026, 11, 14), is_finished_day=True)
