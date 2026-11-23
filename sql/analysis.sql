-- =========================================================================
-- Flood Watch - seven questions for the loaded data (T-SQL, SQL Server)
-- Run against DE_Learning after the pipeline has loaded 13-15 Nov 2026.
-- =========================================================================

-- -------------------------------------------------------------------------
-- Q1. What is the newest reading we hold for each measuring device?
--     "Current" attributes live on the is_current = 1 version of the station.
-- -------------------------------------------------------------------------
WITH latest AS (
    SELECT r.measure_key, r.value, r.reading_at_utc,
           ROW_NUMBER() OVER (PARTITION BY r.measure_key
                              ORDER BY r.reading_at_utc DESC) AS rn
    FROM flood.fact_reading AS r
)
SELECT s.label            AS station,
       m.qualifier        AS measure,
       m.unit_name        AS unit,
       l.value            AS latest_value,
       l.reading_at_utc   AS latest_reading_utc
FROM latest AS l
JOIN flood.dim_measure AS m ON m.measure_key = l.measure_key
JOIN flood.dim_station AS s ON s.station_key = m.station_key AND s.is_current = 1
WHERE l.rn = 1
ORDER BY s.label;
GO

-- Q2. How much did each measure move between the first and last COMPLETE day?
--     "Complete" is measured against the best day we hold, not against a
--     number we guessed: 96 x 35 would be wrong, because five devices in the
--     metadata never report anything at all.
-- -------------------------------------------------------------------------
WITH day_totals AS (
    SELECT reading_date, COUNT(*) AS readings
    FROM flood.fact_reading
    GROUP BY reading_date
),
threshold AS (
    SELECT MAX(readings) * 0.9 AS minimum FROM day_totals
),
complete_days AS (
    SELECT d.reading_date
    FROM day_totals AS d CROSS JOIN threshold AS t
    WHERE d.readings >= t.minimum
),
ranked AS (
    SELECT r.measure_key, r.value, r.reading_at_utc,
           ROW_NUMBER() OVER (PARTITION BY r.measure_key
                              ORDER BY r.reading_at_utc ASC)  AS first_row,
           ROW_NUMBER() OVER (PARTITION BY r.measure_key
                              ORDER BY r.reading_at_utc DESC) AS last_row
    FROM flood.fact_reading AS r
    JOIN complete_days AS d ON d.reading_date = r.reading_date
)
SELECT s.label                            AS station,
       m.qualifier                        AS measure,
       m.unit_name                        AS unit,
       CAST(f.value AS DECIMAL(9,3))      AS first_value,
       CAST(l.value AS DECIMAL(9,3))      AS last_value,
       CAST(l.value - f.value AS DECIMAL(9,3)) AS change,
       CASE WHEN l.value > f.value THEN 'rising'
            WHEN l.value < f.value THEN 'falling'
            ELSE 'flat' END               AS direction
FROM ranked AS f
JOIN ranked AS l ON l.measure_key = f.measure_key AND l.last_row = 1
JOIN flood.dim_measure AS m ON m.measure_key = f.measure_key
JOIN flood.dim_station AS s ON s.station_key = m.station_key AND s.is_current = 1
WHERE f.first_row = 1
ORDER BY ABS(l.value - f.value) DESC;
GO

-- -------------------------------------------------------------------------
-- Q3. Which devices are missing readings, and on which days?
--     Expected count per day = 24 * 60 / 15 = 96.
-- -------------------------------------------------------------------------
WITH loaded_days AS (
    SELECT DISTINCT day_loaded
    FROM flood.pipeline_runs
    WHERE status = 'success'
),
measure_days AS (
    SELECT d.day_loaded, m.measure_key, m.station_key, m.qualifier
    FROM loaded_days AS d
    CROSS JOIN flood.dim_measure AS m
),
measure_counts AS (
    SELECT md.day_loaded, md.measure_key, md.station_key, md.qualifier,
           COUNT(r.measure_key) AS readings_held
    FROM measure_days AS md
    LEFT JOIN flood.fact_reading AS r
           ON r.measure_key = md.measure_key
          AND r.reading_date = md.day_loaded
    GROUP BY md.day_loaded, md.measure_key, md.station_key, md.qualifier
)
SELECT c.day_loaded                    AS day,
       s.label                         AS station,
       c.qualifier                     AS measure,
       c.readings_held                 AS readings_held,
       96 - c.readings_held            AS readings_missing
FROM measure_counts AS c
JOIN flood.dim_station AS s
     ON s.station_key = c.station_key
    AND s.is_current = 1
WHERE c.readings_held < 96
ORDER BY readings_missing DESC, s.label;
GO

-- -------------------------------------------------------------------------
-- Q4. Which stations have more than one version, and what changed?
--     This is the type-2 dimension paying for itself.
-- -------------------------------------------------------------------------
SELECT s.notation        AS station_ref,
       s.label           AS station,
       s.catchment_name  AS catchment,
       s.station_status  AS status,
       s.valid_from      AS valid_from,
       s.valid_to        AS valid_to,
       s.is_current      AS is_current
FROM flood.dim_station AS s
WHERE s.notation IN (
        SELECT notation FROM flood.dim_station
        GROUP BY notation HAVING COUNT(*) > 1)
ORDER BY s.notation, s.valid_from;
GO

-- -------------------------------------------------------------------------
-- Q4b. The "as of" pattern: what did the station look like on 14 November?
--      This is the query a type-2 dimension exists to make possible.
-- -------------------------------------------------------------------------
SELECT s.label, s.river_name, s.catchment_name, s.station_status
FROM flood.dim_station AS s
WHERE '2026-11-14' BETWEEN s.valid_from AND s.valid_to
ORDER BY s.label;
GO

-- -------------------------------------------------------------------------
-- Q5. Peak and lowest level per river - but only within one unit.
--     mASD (metres above station datum) and mAOD (metres above ordnance
--     datum) are different rulers. Adding them together is meaningless.
-- -------------------------------------------------------------------------
SELECT s.river_name                AS river,
       m.unit_name                 AS unit,
       COUNT(DISTINCT s.station_key) AS stations,
       COUNT(*)                    AS readings,
       CAST(MIN(r.value) AS DECIMAL(9,3)) AS lowest,
       CAST(MAX(r.value) AS DECIMAL(9,3)) AS peak
FROM flood.fact_reading AS r
JOIN flood.dim_measure AS m ON m.measure_key = r.measure_key
JOIN flood.dim_station AS s ON s.station_key = m.station_key AND s.is_current = 1
WHERE m.unit_name = 'mASD'
GROUP BY s.river_name, m.unit_name
ORDER BY peak DESC;
GO

-- -------------------------------------------------------------------------
-- Q6. Does any suspended station keep sending readings?
--     Note the join: the fact row is matched to the station version that was
--     valid ON THE DAY IT WAS MEASURED, not to today's version. Join on
--     is_current = 1 instead and historical station versions are excluded.
--     The current snapshots contain no suspended versions, so this returns
--     no rows for this dataset.
-- -------------------------------------------------------------------------
SELECT s.label              AS station,
       s.station_status     AS status,
       s.valid_from         AS version_from,
       s.valid_to           AS version_to,
       COUNT(*)             AS readings_while_suspended,
       MIN(r.reading_at_utc) AS first_reading,
       MAX(r.reading_at_utc) AS last_reading
FROM flood.fact_reading AS r
JOIN flood.dim_station AS s
     ON s.station_key = r.station_key
    AND r.reading_date BETWEEN s.valid_from AND s.valid_to
WHERE s.station_status = 'Suspended'
GROUP BY s.label, s.station_status, s.valid_from, s.valid_to;
GO

-- -------------------------------------------------------------------------
-- Q7. Why units matter: the same "maximum level" by unit.
--     One number per unit, never one number for all of them.
-- -------------------------------------------------------------------------
SELECT m.unit_name                  AS unit,
       COUNT(DISTINCT m.measure_key) AS measures,
       CAST(MIN(r.value) AS DECIMAL(9,3)) AS lowest,
       CAST(MAX(r.value) AS DECIMAL(9,3)) AS highest,
       CAST(AVG(r.value) AS DECIMAL(9,3)) AS average
FROM flood.fact_reading AS r
JOIN flood.dim_measure AS m ON m.measure_key = r.measure_key
GROUP BY m.unit_name
ORDER BY measures DESC;
GO

-- -------------------------------------------------------------------------
-- Q8. The pipeline's own audit trail.
-- -------------------------------------------------------------------------
SELECT run_id, day_loaded, readings_loaded, stations_loaded, status, message
FROM flood.pipeline_runs
ORDER BY run_id DESC;
GO
