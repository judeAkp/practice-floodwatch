-- =========================================================================
-- Flood Watch - tables for the DE_Learning database
-- Run once in SSMS, or let src/load.py run it for you.
-- Everything lives in its own schema so it cannot collide with the tables
-- you built in Week 4 (which live in dbo).
-- =========================================================================

IF SCHEMA_ID('flood') IS NULL
    EXEC ('CREATE SCHEMA flood AUTHORIZATION dbo');
GO

-- This file is also run by every load. Keep it additive: never drop loaded data.
-- -------------------------------------------------------------------------
-- Station dimension: TYPE 2. One row per station per version.
-- The key is (station_key, valid_from) because a station has many versions.
-- -------------------------------------------------------------------------
IF OBJECT_ID('flood.dim_station', 'U') IS NULL
BEGIN
    CREATE TABLE flood.dim_station (
        station_key      INT            NOT NULL,
        notation         VARCHAR(20)    NOT NULL,
        label            NVARCHAR(100)  NULL,
        river_name       NVARCHAR(100)  NULL,
        catchment_name   NVARCHAR(100)  NULL,
        town             NVARCHAR(100)  NULL,
        latitude         DECIMAL(9,6)   NULL,
        longitude        DECIMAL(9,6)   NULL,
        date_opened      DATE           NULL,
        station_status   VARCHAR(30)    NULL,
        valid_from       DATE           NOT NULL,
        valid_to         DATE           NOT NULL,
        is_current       BIT            NOT NULL,
        row_hash         CHAR(16)       NOT NULL,
        CONSTRAINT PK_dim_station PRIMARY KEY (station_key, valid_from),
        CONSTRAINT CK_dim_station_dates CHECK (valid_to >= valid_from),
        CONSTRAINT CK_dim_station_current CHECK (is_current IN (0, 1))
    );
END;
GO

-- -------------------------------------------------------------------------
-- Measure dimension: one row per measuring device.
-- This is where 35 rows come from - not 31. Some stations measure twice.
-- -------------------------------------------------------------------------
IF OBJECT_ID('flood.dim_measure', 'U') IS NULL
BEGIN
    CREATE TABLE flood.dim_measure (
        measure_key      INT          NOT NULL,
        measure_id       VARCHAR(80)  NOT NULL,
        station_key      INT          NOT NULL,
        station_notation VARCHAR(20)  NOT NULL,
        qualifier        NVARCHAR(50) NULL,
        unit_name        VARCHAR(10)  NOT NULL,
        period_minutes   TINYINT      NOT NULL,
        CONSTRAINT PK_dim_measure PRIMARY KEY (measure_key),
        CONSTRAINT UQ_dim_measure_id UNIQUE (measure_id)
    );
END;
GO

IF OBJECT_ID('flood.dim_date', 'U') IS NULL
BEGIN
    CREATE TABLE flood.dim_date (
        date_key      INT         NOT NULL,
        full_date     DATE        NOT NULL,
        year          SMALLINT    NOT NULL,
        month         TINYINT     NOT NULL,
        day_of_month  TINYINT     NOT NULL,
        day_name      VARCHAR(10) NOT NULL,
        is_weekend    BIT         NOT NULL,
        CONSTRAINT PK_dim_date PRIMARY KEY (date_key)
    );
END;
GO

-- -------------------------------------------------------------------------
-- Reading fact: one row per measure per 15-minute period.
-- -------------------------------------------------------------------------
IF OBJECT_ID('flood.fact_reading', 'U') IS NULL
BEGIN
    CREATE TABLE flood.fact_reading (
        measure_key     INT           NOT NULL,
        station_key     INT           NOT NULL,
        reading_at_utc  DATETIME2(0)  NOT NULL,
        reading_date    DATE          NOT NULL,   -- local (Europe/London) day
        value           DECIMAL(9,3)  NOT NULL,
        CONSTRAINT PK_fact_reading PRIMARY KEY (measure_key, reading_at_utc)
    );
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('flood.fact_reading')
      AND name = 'IX_fact_reading_date'
)
    CREATE INDEX IX_fact_reading_date ON flood.fact_reading (reading_date);

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('flood.fact_reading')
      AND name = 'IX_fact_reading_station'
)
    CREATE INDEX IX_fact_reading_station ON flood.fact_reading (station_key, reading_at_utc);
GO

-- -------------------------------------------------------------------------
-- Pipeline bookkeeping
-- -------------------------------------------------------------------------
IF OBJECT_ID('flood.load_watermark', 'U') IS NULL
BEGIN
    CREATE TABLE flood.load_watermark (
        pipeline_name    VARCHAR(50) NOT NULL,
        last_day_loaded  DATE        NULL,
        updated_at_utc   DATETIME2(0) NOT NULL,
        CONSTRAINT PK_load_watermark PRIMARY KEY (pipeline_name)
    );
END;
GO

IF OBJECT_ID('flood.pipeline_runs', 'U') IS NULL
BEGIN
    CREATE TABLE flood.pipeline_runs (
        run_id            INT IDENTITY(1,1) PRIMARY KEY,
        pipeline_name     VARCHAR(50)  NOT NULL,
        run_started_utc   DATETIME2(0) NOT NULL,
        run_finished_utc  DATETIME2(0) NULL,
        day_loaded        DATE         NOT NULL,
        readings_loaded   INT          NULL,
        stations_loaded   INT          NULL,
        status            VARCHAR(10)  NOT NULL,
        message           NVARCHAR(400) NULL
    );
END;
GO
