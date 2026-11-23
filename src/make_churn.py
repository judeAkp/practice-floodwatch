"""Create extra station snapshots so you can see a type-2 dimension work.

The real API does not change three stations in three days. Slow-changing
attributes are called slow for a reason. So this tool copies the genuine
snapshot and applies three edits that the Environment Agency really does make:

  1. a station is suspended (sensor under maintenance)
  2. a missing catchment name is filled in later by the publisher
  3. a station is renamed / reinstated afterwards

Snapshot 2026-11-13 is untouched real API data. Snapshots 14 and 15 are that
same real data plus the edits below, and this file is the receipt: you can see
exactly what was changed, and the pipeline cannot tell the difference between a
simulated change and a real one.
"""

import json
from copy import deepcopy
from pathlib import Path

from config import STATION_DIR

SUSPEND = "http://environment.data.gov.uk/flood-monitoring/def/core/statusSuspended"
ACTIVE = "http://environment.data.gov.uk/flood-monitoring/def/core/statusActive"


def _find(items, notation):
    for item in items:
        if item["notation"] == notation:
            return item
    raise KeyError(f"station {notation} is not in the snapshot")


def make_day_two(day_one):
    payload = deepcopy(day_one)
    items = payload["items"]

    _find(items, "4172")["status"] = SUSPEND            # 1. sensor under maintenance

    homeless = next(i for i in items if not i.get("catchmentName"))
    homeless["catchmentName"] = "Tame Anker and Mease"  # 2. publisher fills a gap

    _find(items, "2538")["label"] = "Halesowen, Manor Way"   # 3. station renamed
    return payload


def make_day_three(day_two):
    payload = deepcopy(day_two)
    _find(payload["items"], "4172")["status"] = ACTIVE  # reinstated, third version
    return payload


def main():
    source = Path(STATION_DIR) / "2026-11-13.json"
    day_one = json.loads(source.read_text(encoding="utf-8"))
    day_two = make_day_two(day_one)
    day_three = make_day_three(day_two)

    for name, payload in (("2026-11-14", day_two), ("2026-11-15", day_three)):
        path = Path(STATION_DIR) / f"{name}.json"
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {path.name}")


if __name__ == "__main__":
    main()
