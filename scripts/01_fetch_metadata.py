"""[A] Fetch GSI vertical-photo metadata (GeoJSON) and write datasets/<proj>/photos.csv.

Usage:
  python scripts/01_fetch_metadata.py --layer 20240102noto_suzu_0102suichoku --project suzu_0102

The GeoJSON at /2/3/1.geojson contains every photo of the layer as a Point feature.
Property keys are Japanese (UTF-8). We locate them by substring so minor label
changes on GSI's side do not break the parser.
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATASETS_DIR, USER_AGENT, PhotoRecord, haversine_m,  # noqa: E402
                    parse_jp_datetime, write_photos_csv)

GEOJSON_URL = "https://maps.gsi.go.jp/xyz/{layer}/2/3/1.geojson"
PHOTO_BASE = "https://saigai.gsi.go.jp/1/"
# <a href="https://saigai.gsi.go.jp/1/index_dmc.html?R6_0101notohanto/0102suzu_DMC/photo/qv/0001.jpg&269.417deg">
_IMG_RE = re.compile(r"index_[a-z0-9_]+\.html\?([^&\"']+)&([-0-9.]+)deg")


def _prop(props: dict, *needles: str) -> str:
    for k, v in props.items():
        if any(n in k for n in needles):
            return v if isinstance(v, str) else str(v)
    return ""


def parse_feature(feat: dict) -> PhotoRecord | None:
    props = feat.get("properties", {})
    geom = feat.get("geometry", {})
    if geom.get("type") != "Point":
        return None
    lon, lat = geom["coordinates"][:2]
    html = _prop(props, "画像")
    m = _IMG_RE.search(html)
    if not m:
        return None
    rel_path, rot = m.group(1), float(m.group(2))
    course = _prop(props, "コース").strip()
    photo_no = _prop(props, "写真番号").strip()
    shot_time = parse_jp_datetime(_prop(props, "撮影"))
    fname = f"{course}_{photo_no}.jpg"
    return PhotoRecord(
        file=fname, url=PHOTO_BASE + rel_path, lon=float(lon), lat=float(lat),
        course=course, photo_no=photo_no, shot_time=shot_time, rotation_deg=rot,
    )


def geometry_report(recs: list[PhotoRecord]) -> None:
    by_course: dict[str, list[PhotoRecord]] = defaultdict(list)
    for r in recs:
        by_course[r.course].append(r)
    print(f"photos: {len(recs)}  courses: {len(by_course)}")
    lons = [r.lon for r in recs]
    lats = [r.lat for r in recs]
    print(f"bbox: lon {min(lons):.4f}..{max(lons):.4f}  lat {min(lats):.4f}..{max(lats):.4f}")

    along: list[float] = []
    for c, rs in sorted(by_course.items()):
        rs.sort(key=lambda r: r.photo_no)
        d = [haversine_m(a.lon, a.lat, b.lon, b.lat) for a, b in zip(rs, rs[1:])]
        along += d
        med = statistics.median(d) if d else float("nan")
        print(f"  {c}: {len(rs):3d} photos, along-track spacing median {med:7.1f} m")
    if along:
        print(f"along-track spacing (all): median {statistics.median(along):.1f} m")

    # across-track: for each photo, nearest photo of a *different* course
    across: list[float] = []
    for r in recs:
        best = min(
            (haversine_m(r.lon, r.lat, o.lon, o.lat) for o in recs if o.course != r.course),
            default=float("nan"),
        )
        across.append(best)
    if across:
        print(f"across-track (nearest other-course photo): median {statistics.median(across):.1f} m")

    times = sorted(r.shot_time for r in recs if r.shot_time)
    if times:
        print(f"shot time: {times[0]} .. {times[-1]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layer", required=True, action="append",
                    help="GSI layer id, e.g. 20240102noto_suzu_0102suichoku (repeatable)")
    ap.add_argument("--project", required=True, help="dataset name under datasets/")
    ap.add_argument("--datasets-dir", type=Path, default=DATASETS_DIR)
    args = ap.parse_args()

    recs: list[PhotoRecord] = []
    sess = requests.Session()
    sess.headers["User-Agent"] = USER_AGENT
    for layer in args.layer:
        url = GEOJSON_URL.format(layer=layer)
        r = sess.get(url, timeout=60)
        r.raise_for_status()
        feats = r.json().get("features", [])
        parsed = [p for p in (parse_feature(f) for f in feats) if p]
        print(f"{layer}: {len(feats)} features -> {len(parsed)} photos")
        if len(parsed) != len(feats):
            print("  WARNING: some features could not be parsed", file=sys.stderr)
        recs += parsed

    # de-dup by file name, stable order by course/photo_no
    seen: dict[str, PhotoRecord] = {}
    for r in recs:
        seen.setdefault(r.file, r)
    recs = sorted(seen.values(), key=lambda r: (r.course, r.photo_no))

    out = args.datasets_dir / args.project / "photos.csv"
    write_photos_csv(out, recs)
    print(f"wrote {out} ({len(recs)} rows)")
    geometry_report(recs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
