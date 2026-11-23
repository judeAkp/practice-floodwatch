"""Write the four tables into SQL Server, safely and repeatably.

Rules this file obeys:

  * dimensions are rebuilt from raw files (cheap, and correct every time)
  * a fact load replaces exactly one day, so re-running a day is harmless
  * everything happens inside one transaction: all of it, or none of it
  * every run leaves a row in flood.pipeline_runs
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from config import DATABASE_NAME, PIPELINE_NAME, PROJECT_ROOT

DDL_PATH = PROJECT_ROOT / "sql" / "ddl.sql"


def get_engine():
    """Connect to SQL Server with Windows authentication.

    The connection string is the only line that knows where the database lives.
    """
    return create_engine(
        f"mssql+pyodbc://./{DATABASE_NAME}"
        "?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes"
        "&TrustServerCertificate=yes",
        fast_executemany=True,
    )


def ensure_tables(engine):
    """Run sql/ddl.sql once, batch by batch.

    SSMS treats the word GO as "end of batch"; the driver does not, so we split
    the file on it ourselves and send each piece separately. Batches that hold
    nothing but comments are skipped, because SQL Server rejects an empty batch.
    """
    script = DDL_PATH.read_text(encoding="utf-8")
    batches = []
    for batch in script.split("GO"):
        statements = [line for line in batch.splitlines()
                      if line.strip() and not line.strip().startswith("--")]
        if statements:
            batches.append(batch.strip())

    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        for batch in batches:
            cursor.execute(batch)
        raw.commit()
    finally:
        raw.close()


def load_dimensions(conn, dim_station, dim_measure, dim_date):
    """Replace the three dimensions. Small tables, so a full rebuild is fine."""
    conn.execute(text("DELETE FROM flood.dim_station"))
    conn.execute(text("DELETE FROM flood.dim_measure"))

    dim_station.to_sql("dim_station", conn, schema="flood",
                       if_exists="append", index=False, chunksize=500)
    dim_measure.to_sql("dim_measure", conn, schema="flood",
                       if_exists="append", index=False, chunksize=500)

    # dim_date is additive: never delete it, only fill in days we have not seen.
    existing = {row[0] for row in conn.execute(
        text("SELECT full_date FROM flood.dim_date")).fetchall()}
    missing = dim_date[~dim_date["full_date"].isin(existing)]
    if not missing.empty:
        missing.to_sql("dim_date", conn, schema="flood",
                       if_exists="append", index=False)


def load_day(conn, fact, day):
    """Delete this day's rows, then insert the new ones."""
    conn.execute(text("DELETE FROM flood.fact_reading WHERE reading_date = :day"),
                 {"day": day})
    if not fact.empty:
        fact.to_sql("fact_reading", conn, schema="flood",
                    if_exists="append", index=False, chunksize=1000)


def update_watermark(conn, day):
    """Remember the newest complete day this pipeline has loaded."""
    conn.execute(text("""
        MERGE flood.load_watermark AS target
        USING (SELECT :pipeline AS pipeline_name) AS source
            ON target.pipeline_name = source.pipeline_name
        WHEN MATCHED AND target.last_day_loaded < :day THEN
            UPDATE SET last_day_loaded = :day, updated_at_utc = SYSUTCDATETIME()
        WHEN NOT MATCHED THEN
            INSERT (pipeline_name, last_day_loaded, updated_at_utc)
            VALUES (:pipeline, :day, SYSUTCDATETIME());
    """), {"pipeline": PIPELINE_NAME, "day": day})


def verify_counts(conn, fact, day):
    """The database must hold exactly what we just handed it."""
    expected = len(fact)
    actual = conn.execute(
        text("SELECT COUNT(*) FROM flood.fact_reading WHERE reading_date = :day"),
        {"day": day}).scalar()
    if actual != expected:
        raise RuntimeError(f"verification failed: hoped for {expected} rows on {day}, "
                           f"database has {actual}")


def record_run(conn, day, rows_readings, rows_stations, started, status, message):
    conn.execute(text("""
        INSERT INTO flood.pipeline_runs
            (pipeline_name, run_started_utc, run_finished_utc, day_loaded,
             readings_loaded, stations_loaded, status, message)
        VALUES (:pipeline, :started, SYSUTCDATETIME(), :day, :readings, :stations,
                :status, :message);
    """), {"pipeline": PIPELINE_NAME, "started": started, "day": day,
           "readings": rows_readings, "stations": rows_stations,
           "status": status, "message": message})


def load_all(dim_station, dim_measure, dim_date, fact, day):
    """One transaction around every write."""
    engine = get_engine()
    ensure_tables(engine)
    started = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    with engine.begin() as conn:
        load_dimensions(conn, dim_station, dim_measure, dim_date)
        load_day(conn, fact, day)
        verify_counts(conn, fact, day)
        update_watermark(conn, day)
        record_run(conn, day, len(fact), len(dim_station), started,
                   "success", "quality checks passed")

    print(f"loaded {len(fact):,} readings for {day}, "
          f"{len(dim_station)} station versions, {len(dim_measure)} measures")
    return len(fact)
