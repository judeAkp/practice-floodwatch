"""Turn raw JSON into four clean tables: dim_station, dim_measure,
dim_date and fact_reading.

Everything here is a pure function: data in, DataFrame out, no database, no
network, no clock of its own. That is what makes it testable.

The one idea that drives this file: the station dimension is built by REPLAYING
every snapshot we have ever saved, in date order. Replay means a full rebuild,
and a full rebuild is idempotent by construction - run it ten times and you get
the same history every time.
"""

import hashlib
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import EXPECTED_READINGS_PER_DAY

LOCAL_TZ = ZoneInfo("Europe/London")
END_OF_TIME = date(9999, 12, 31)

# Attributes that describe a station rather than measure its water.
STATION_ATTRIBUTES = ["label", "river_name", "catchment_name", "town",
                      "latitude", "longitude", "date_opened", "station_status"]


class DataQualityError(RuntimeError):
    """Raised when the data fails a check that must stop the load."""

    def __init__(self, failures):
        self.failures = list(failures)
        super().__init__("; ".join(self.failures))


def _clean_text(value):
    """Turn None, '' and 'None' into a real None; strip stray spaces."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _status_name(uri):
    """'http://.../def/core/statusActive' -> 'Active'.

    Ten of our stations have no status field at all, which is why this accepts
    None and returns None instead of blowing up.
    """
    if not uri:
        return None
    return str(uri).rsplit("/", 1)[-1].replace("status", "")


# --------------------------------------------------------------------------
# Stations -> dimension with history
# --------------------------------------------------------------------------
def as_date(value):
    """Accept a date, a datetime or an ISO string and always return a date.

    Snapshot keys arrive as strings from the filename ('2026-11-14'); the
    arithmetic below needs real dates. Sorting strings happens to work here,
    but '2026-11-14' - 1 day does not.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def station_rows(payload):
    """Normalise one snapshot's items into flat dictionaries."""
    rows = []
    for item in payload.get("items", []):
        rows.append({
            "notation": _clean_text(item.get("notation")),
            "label": _clean_text(item.get("label")),
            "river_name": _clean_text(item.get("riverName")),
            "catchment_name": _clean_text(item.get("catchmentName")),
            "town": _clean_text(item.get("town")),
            "latitude": item.get("lat"),
            "longitude": item.get("long"),
            "date_opened": _clean_text(item.get("dateOpened")),
            "station_status": _status_name(item.get("status")),
        })
    return rows


def station_hash(row):
    """A short fingerprint of the attributes we care about.

    Two snapshots with the same fingerprint are the same version of a station.
    Padding with '|' stops ('ab','c') and ('a','bc') colliding.
    """
    joined = "|".join("" if row[a] is None else str(row[a]) for a in STATION_ATTRIBUTES)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def build_dim_station(snapshots):
    """Replay station snapshots into a slowly changing dimension (type 2).

    snapshots: {date: payload} - every snapshot file we have, any order.

    Returns a DataFrame with one row per station per VERSION, where a new
    version starts on the first snapshot date on which an attribute changed.
    """
    if not snapshots:
        raise DataQualityError(["no station snapshots to build the dimension from"])
    snapshots = {as_date(key): payload for key, payload in snapshots.items()}

    versions = []          # finished rows
    open_versions = {}     # notation -> row dict that is still current

    for snapshot_date in sorted(snapshots):
        for row in station_rows(snapshots[snapshot_date]):
            notation = row["notation"]
            if notation is None:
                continue
            fingerprint = station_hash(row)
            current = open_versions.get(notation)

            if current is None:                                  # brand new station
                open_versions[notation] = {**row, "row_hash": fingerprint,
                                           "valid_from": snapshot_date,
                                           "valid_to": END_OF_TIME, "is_current": 1}
            elif current["row_hash"] != fingerprint:             # attribute changed
                current["valid_to"] = snapshot_date - timedelta(days=1)
                current["is_current"] = 0
                versions.append(current)
                open_versions[notation] = {**row, "row_hash": fingerprint,
                                           "valid_from": snapshot_date,
                                           "valid_to": END_OF_TIME, "is_current": 1}

    versions.extend(open_versions.values())

    import pandas as pd

    frame = pd.DataFrame(versions).sort_values(["notation", "valid_from"])
    frame = frame.reset_index(drop=True)
    # Deterministic key: the same notation always gets the same number.
    keys = {notation: index + 1 for index, notation
            in enumerate(sorted(frame["notation"].unique()))}
    frame.insert(0, "station_key", frame["notation"].map(keys).astype("int64"))
    return frame[[ "station_key", "notation", "label", "river_name", "catchment_name",
                   "town", "latitude", "longitude", "date_opened", "station_status",
                   "valid_from", "valid_to", "is_current", "row_hash"]]


# --------------------------------------------------------------------------
# Measures -> dimension
# --------------------------------------------------------------------------
def build_dim_measure(payload_or_measures):
    """One row per measure (station + qualifier + unit + period)."""
    import pandas as pd

    from src.extract import measures_in
    measures = (measures_in(payload_or_measures)
                if isinstance(payload_or_measures, dict) else payload_or_measures)

    unique = {m["measure_id"]: m for m in measures}
    frame = pd.DataFrame([unique[k] for k in sorted(unique)])
    frame["station_key"] = frame["station_notation"].map(
        {n: i + 1 for i, n in enumerate(sorted(frame["station_notation"].unique()))}
    ).astype("int64")
    frame["period_minutes"] = (frame["period_seconds"] / 60).astype("Int64")
    frame = frame.sort_values("measure_id").reset_index(drop=True)
    frame.insert(0, "measure_key", range(1, len(frame) + 1))
    return frame[["measure_key", "measure_id", "station_key", "station_notation",
                  "qualifier", "unit_name", "period_minutes"]]


# --------------------------------------------------------------------------
# Dates -> dimension
# --------------------------------------------------------------------------
def build_dim_date(start, end):
    """One row per calendar day, with the weekday facts you always regroup by."""
    import pandas as pd

    days = pd.date_range(start=start, end=end, freq="D")
    frame = pd.DataFrame({"full_date": days.date})
    frame.insert(0, "date_key", [int(d.strftime("%Y%m%d")) for d in days])
    frame["year"] = days.year
    frame["month"] = days.month
    frame["day_of_month"] = days.day
    frame["day_name"] = [d.strftime("%A") for d in days]
    frame["is_weekend"] = (days.dayofweek >= 5).astype(int)
    return frame


# --------------------------------------------------------------------------
# Readings -> fact
# --------------------------------------------------------------------------
def local_day(utc_text):
    """UTC timestamp -> Europe/London calendar date.

    The API reports UTC. At 23:30 UTC on 14 November it is already the 15th in
    London during British Summer Time, so the storage point and the reporting
    day are two different things.
    """
    import pandas as pd

    stamp = pd.Timestamp(utc_text)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert(LOCAL_TZ).date()


def build_fact_reading(readings, dim_measure):
    """Clean readings and attach the surrogate keys.

    Returns (fact_frame, rejections) where rejections is a list of dicts
    explaining every row we refused to load.
    """
    import pandas as pd

    measure_key = dict(zip(dim_measure["measure_id"], dim_measure["measure_key"]))
    station_key = dict(zip(dim_measure["measure_id"], dim_measure["station_key"]))

    rows, rejections = [], []
    for reading in readings:
        measure_id = reading.get("measure_id")
        if measure_id not in measure_key:
            rejections.append({**reading, "reason": "measure not in dim_measure"})
            continue
        value = reading.get("value")
        if value is None or str(value).strip() == "":
            rejections.append({**reading, "reason": "value is null"})
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            rejections.append({**reading, "reason": "value is not a number"})
            continue
        if not -200 <= value <= 200:
            rejections.append({**reading, "reason": "value outside plausible range"})
            continue

        rows.append({
            "measure_key": measure_key[measure_id],
            "station_key": station_key[measure_id],
            "reading_at_utc": pd.Timestamp(reading["dateTime"])
                                .tz_convert("UTC").tz_localize(None),
            "reading_date": local_day(reading["dateTime"]),
            "value": value,
        })

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, rejections

    # Same measure, same timestamp, twice -> keep the last one we saw.
    before = len(frame)
    frame = (frame.sort_values(["measure_key", "reading_at_utc"])
                  .drop_duplicates(subset=["measure_key", "reading_at_utc"],
                                   keep="last")
                  .reset_index(drop=True))
    duplicates = before - len(frame)
    if duplicates:
        rejections.append({"reason": f"{duplicates} duplicate readings collapsed"})
    return frame, rejections


def completeness_gaps(fact, day):
    """How many readings each measure should have had on a finished day."""
    if fact.empty:
        import pandas as pd

        return pd.DataFrame(columns=["measure_key", "readings", "missing"])
    per_measure = fact.groupby("measure_key").size().rename("readings")
    frame = per_measure.reset_index()
    frame["missing"] = (EXPECTED_READINGS_PER_DAY - frame["readings"]).clip(lower=0)
    return frame


def quality_checks(fact, day, is_finished_day):
    """Checks that stop the load. Raise once, with every failure listed."""
    failures = []

    if fact.empty:
        failures.append(f"{day}: no readings survived cleaning")
        raise DataQualityError(failures)

    duplicated = fact.duplicated(subset=["measure_key", "reading_at_utc"]).sum()
    if duplicated:
        failures.append(f"{day}: {duplicated} duplicate (measure, timestamp) rows")

    if fact["value"].isna().any():
        failures.append(f"{day}: null values reached the fact table")

    off_day = (fact["reading_date"] != day).sum()
    if is_finished_day and off_day:
        failures.append(f"{day}: {off_day} readings fall outside the requested local day")

    if is_finished_day:
        per_measure = fact.groupby("measure_key").size()
        short = per_measure[per_measure < EXPECTED_READINGS_PER_DAY * 0.5]
        if not short.empty:
            failures.append(f"{day}: {len(short)} measures returned less than half "
                            f"a day of readings ({', '.join(short.index.astype(str).head(5))})")

    if failures:
        raise DataQualityError(failures)
