"""Settings for the Flood Watch pipeline.

Every other module imports its paths and constants from here, so there is
exactly one place to change when something moves.
"""

from pathlib import Path

# --- Where we get the data -------------------------------------------------
API_BASE = "https://environment.data.gov.uk/flood-monitoring"

# A radius search around Birmingham city centre. Change these three numbers
# and the whole project follows a different patch of the country.
SEARCH_LATITUDE = 52.4796
SEARCH_LONGITUDE = -1.9026
SEARCH_RADIUS_KM = 15

# Readings arrive every 15 minutes -> 96 possible readings per station per day.
READING_INTERVAL_MINUTES = 15
EXPECTED_READINGS_PER_DAY = 24 * 60 // READING_INTERVAL_MINUTES  # 96

# --- Where things are stored ----------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
STATION_DIR = RAW_DIR / "stations"
READING_DIR = RAW_DIR / "readings"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

# --- Warehouse -------------------------------------------------------------
DATABASE_NAME = "DE_Learning"
PIPELINE_NAME = "flood_watch"

# --- Politeness ------------------------------------------------------------
REQUEST_TIMEOUT_SECONDS = 45
MAX_ATTEMPTS = 4
SECONDS_BETWEEN_REQUESTS = 0.15
"""Settings for the Flood Watch pipeline.

Every other module imports its paths and constants from here, so there is
exactly one place to change when something moves.
"""

from pathlib import Path

# --- Where we get the data -------------------------------------------------
API_BASE = "https://environment.data.gov.uk/flood-monitoring"

# A radius search around Birmingham city centre. Change these three numbers
# and the whole project follows a different patch of the country.
SEARCH_LATITUDE = 52.4796
SEARCH_LONGITUDE = -1.9026
SEARCH_RADIUS_KM = 15

# Readings arrive every 15 minutes -> 96 possible readings per station per day.
READING_INTERVAL_MINUTES = 15
EXPECTED_READINGS_PER_DAY = 24 * 60 // READING_INTERVAL_MINUTES  # 96

# --- Where things are stored ----------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
STATION_DIR = RAW_DIR / "stations"
READING_DIR = RAW_DIR / "readings"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

# --- Warehouse -------------------------------------------------------------
DATABASE_NAME = "DE_Learning"
PIPELINE_NAME = "flood_watch"

# --- Politeness ------------------------------------------------------------
REQUEST_TIMEOUT_SECONDS = 45
MAX_ATTEMPTS = 4
SECONDS_BETWEEN_REQUESTS = 0.15