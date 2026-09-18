"""Shared helpers for the Noto vertical-photo -> ODM pipeline."""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, asdict, fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = REPO_ROOT / "datasets"
USER_AGENT = "odm-aerial-photo-sfm/0.1 (+https://github.com/shiwaku/odm-aerial-photo-sfm)"

PHOTO_CSV_FIELDS = [
    "file", "url", "lon", "lat", "course", "photo_no", "shot_time", "rotation_deg",
]


@dataclass
class PhotoRecord:
    file: str
    url: str
    lon: float
    lat: float
    course: str
    photo_no: str
    shot_time: str
    rotation_deg: float

    @classmethod
    def from_row(cls, row: dict) -> "PhotoRecord":
        return cls(
            file=row["file"],
            url=row["url"],
            lon=float(row["lon"]),
            lat=float(row["lat"]),
            course=row["course"],
            photo_no=row["photo_no"],
            shot_time=row["shot_time"],
            rotation_deg=float(row["rotation_deg"]) if row.get("rotation_deg") not in (None, "") else float("nan"),
        )


def read_photos_csv(path: Path) -> list[PhotoRecord]:
    with path.open(encoding="utf-8", newline="") as f:
        return [PhotoRecord.from_row(r) for r in csv.DictReader(f)]


def write_photos_csv(path: Path, records: list[PhotoRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[fl.name for fl in fields(PhotoRecord)])
        w.writeheader()
        for r in records:
            w.writerow(asdict(r))


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


_JP_TIME = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2})時(\d{1,2})分(\d{1,2})秒")


def parse_jp_datetime(s: str) -> str:
    """'2024年1月2日 11時22分51秒' -> '2024-01-02T11:22:51+09:00'. Returns '' if unparsable."""
    m = _JP_TIME.search(s or "")
    if not m:
        return ""
    y, mo, d, h, mi, se = (int(x) for x in m.groups())
    # GSI data occasionally carries "60秒"; normalise via timedelta.
    from datetime import datetime, timedelta
    base = datetime(y, mo, d) + timedelta(hours=h, minutes=mi, seconds=se)
    return base.strftime("%Y-%m-%dT%H:%M:%S") + "+09:00"
