"""One place that knows how to talk to the Environment Agency API.

Extraction scripts never call urllib directly; they call get_json(). That means
retries, timeouts and politeness are written once and can be tested once.
"""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from config import (API_BASE, MAX_ATTEMPTS, REQUEST_TIMEOUT_SECONDS,
                    SECONDS_BETWEEN_REQUESTS)


class ApiError(RuntimeError):
    """Raised when an endpoint keeps failing after every retry."""


def build_url(path, **params):
    """Join the base URL and a path, then add query parameters.

    build_url("/id/stations", parameter="level", _limit=2)
    -> https://environment.data.gov.uk/flood-monitoring/id/stations?parameter=level&_limit=2
    """
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"
    return url


def get_json(path, **params):
    """GET a URL and return the decoded JSON, retrying on failure."""
    url = build_url(path, **params)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = json.load(response)
            time.sleep(SECONDS_BETWEEN_REQUESTS)  # be a good citizen
            return payload
        except HTTPError as error:
            # A 400 means we asked for something wrong - retrying will not help.
            if error.code == 400:
                raise ApiError(f"the API rejected the request: {url}") from error
            last_error = error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error

        wait = 2 ** attempt  # 2, 4, 8 seconds
        print(f"  attempt {attempt} failed ({type(last_error).__name__}); "
              f"retrying in {wait}s")
        time.sleep(wait)

    raise ApiError(f"gave up after {MAX_ATTEMPTS} attempts: {url}") from last_error
