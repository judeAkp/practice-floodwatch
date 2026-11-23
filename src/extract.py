"""Download station metadata and river-level readings, and save them as files.

Two jobs, one file:

  extract_stations()  - "who and where is everybody?"  (a snapshot, ~30 KB)
  extract_readings()  - "what did the water do yesterday?" (one file per day)

Nothing is cleaned or typed here. The raw response is written to disk exactly
as it arrived, so that a bug in the transform step never forces us to hit the
API again.
"""

import json
from datetime import date, datetime, timezone
from pathlib import Path

from config import READING_DIR, STATION_DIR, SEARCH_LATITUDE, SEARCH_LONGITUDE, SEARCH_RADIUS_KM
from src.api import get_json


# --------------------------------------------------------------------------
# Stations
# --------------------------------------------------------------------------
def fetch_stations():
    """Ask the API for every river-level station within the search radius."""
    return get_json(
        "/id/stations",
        parameter="level",
        lat=SEARCH_LATITUDE,
        long=SEARCH_LONGITUDE,
        dist=SEARCH_RADIUS_KM,
    )


def save_station_snapshot(payload, as_of):
    """Write one snapshot per day: data/raw/stations/2026-11-14.json."""
    STATION_DIR.mkdir(parents=True, exist_ok=True)
    path = Path(STATION_DIR) / f"{as_of.isoformat()}.json"
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def extract_stations(as_of=None):
    """Snapshot today's station metadata. Returns (path, payload)."""
    as_of = as_of or date.today()
    payload = fetch_stations()
    path = save_station_snapshot(payload, as_of)
    print(f"stations  : {len(payload['items']):>4} saved to {path.name}")
    return path, payload


# --------------------------------------------------------------------------
# Readings
# --------------------------------------------------------------------------
def measures_in(payload):
    """Pull every level measure out of a station payload.

    A station can have several measures (upstream stage, downstream stage,
    reservoir level). Each measure is what actually carries readings, so we
    work with measures rather than stations from here on.
    """
    measures = []
    for station in payload["items"]:
        for measure in station.get("measures", []):
            if measure.get("parameter") != "level":
                continue
            measures.append({
                "measure_id": measure["@id"].rsplit("/", 1)[-1],
                "station_notation": station["notation"],
                "qualifier": measure.get("qualifier"),
                "unit_name": measure.get("unitName"),
                "period_seconds": measure.get("period"),
            })
    return measures


def fetch_readings_for_day(day, measures):
    """Fetch one day of readings for every measure: 35 small requests."""
    readings = []
    for position, measure in enumerate(measures, start=1):
        payload = get_json(
            f"/id/measures/{measure['measure_id']}/readings",
            _sorted="",
            startdate=day.isoformat(),
            enddate=day.isoformat(),
        )
        for item in payload.get("items", []):
            readings.append({
                "station_notation": measure["station_notation"],
                "measure_id": measure["measure_id"],
                "dateTime": item["dateTime"],
                "value": item.get("value"),
            })
        if position % 10 == 0:
            print(f"  ... {position}/{len(measures)} measures fetched")
    return readings


def save_readings(readings, day):
    """Write one file per day: data/raw/readings/readings_2026-11-14.json."""
    READING_DIR.mkdir(parents=True, exist_ok=True)
    path = Path(READING_DIR) / f"readings_{day.isoformat()}.json"
    payload = {
        "day": day.isoformat(),
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(readings),
        "readings": readings,
    }
    path.write_text(json.dumps(payload, indent=0), encoding="utf-8")
    return path


def extract_readings(day, station_payload=None):
    """Fetch one day of readings. Returns (path, readings)."""
    if station_payload is None:
        snapshot = Path(STATION_DIR) / f"{day.isoformat()}.json"
        station_payload = json.loads(snapshot.read_text(encoding="utf-8"))
    measures = measures_in(station_payload)
    readings = fetch_readings_for_day(day, measures)
    path = save_readings(readings, day)
    print(f"readings  : {len(readings):>4} rows for {day} saved to {path.name}")
    return path, readings
