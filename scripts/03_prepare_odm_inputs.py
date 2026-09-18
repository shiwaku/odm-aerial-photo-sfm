"""[C] Prepare ODM inputs: EXIF-injected copies in images/, geo.txt, dataset_info.json.

Usage:
  python scripts/03_prepare_odm_inputs.py --project suzu_0102 --camera config/cameras/dmc3_qv.json
      [--agl 4100] [--ground-elev 100] [--sidelap 0.30] [--with-yaw]

The qv JPEGs from GSI have no EXIF. OpenSfM needs GPS and a focal-length hint to
start bundle adjustment from a sane place, so we inject:
  GPSLatitude/Longitude   principal-point coordinates from the GeoJSON
  GPSAltitude             ground elevation + above-ground height (AGL)
  FocalLength             camera focal length in mm
  FocalLengthIn35mmFilm   36 * f / sensor_long_side  (OpenSfM focal ratio)
  Make / Model            so all photos share one camera model
  DateTimeOriginal        shot time

AGL is estimated from course spacing unless --agl is given:
  footprint_across = across_spacing / (1 - sidelap)
  GSD_full         = footprint_across / full_long_px
  AGL              = GSD_full * f / pixel_size
A forward-overlap cross-check is printed for sanity.

geo.txt (ODM --geo) is written with 4 columns (image lon lat alt); horizontal
accuracy is passed globally with --gps-accuracy at run time. --with-yaw writes the
9-column form with yaw derived from the direction of travel (pitch=roll=0).
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

import piexif
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS_DIR, REPO_ROOT, PhotoRecord, haversine_m, read_photos_csv  # noqa: E402


def bearing_deg(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y)) % 360.0


def spacing_stats(recs: list[PhotoRecord]) -> tuple[float, float]:
    by_course: dict[str, list[PhotoRecord]] = defaultdict(list)
    for r in recs:
        by_course[r.course].append(r)
    along = []
    for rs in by_course.values():
        rs.sort(key=lambda r: r.shot_time or r.photo_no)
        along += [haversine_m(a.lon, a.lat, b.lon, b.lat) for a, b in zip(rs, rs[1:])]
    across = [
        min(haversine_m(r.lon, r.lat, o.lon, o.lat) for o in recs if o.course != r.course)
        for r in recs
    ]
    return statistics.median(along), statistics.median(across)


def headings(recs: list[PhotoRecord]) -> dict[str, float]:
    """Heading of travel per photo from time-ordered neighbours within the course."""
    by_course: dict[str, list[PhotoRecord]] = defaultdict(list)
    for r in recs:
        by_course[r.course].append(r)
    out: dict[str, float] = {}
    for rs in by_course.values():
        rs.sort(key=lambda r: r.shot_time or r.photo_no)
        for i, r in enumerate(rs):
            a = rs[i - 1] if i > 0 else r
            b = rs[i + 1] if i + 1 < len(rs) else r
            out[r.file] = float("nan") if a is b else bearing_deg(a.lon, a.lat, b.lon, b.lat)
    return out


def _rat(x: float, den: int = 1_000_000) -> tuple[int, int]:
    f = Fraction(x).limit_denominator(den)
    return f.numerator, f.denominator


def _dms(deg: float):
    deg = abs(deg)
    d = int(deg)
    m_f = (deg - d) * 60
    m = int(m_f)
    s = (m_f - m) * 60
    return (d, 1), (m, 1), _rat(s, 10_000)


def build_exif(r: PhotoRecord, cam: dict, alt_m: float, focal35: int, size: tuple[int, int]) -> bytes:
    dt = r.shot_time[:19].replace("-", ":").replace("T", " ") if r.shot_time else ""
    zeroth = {
        piexif.ImageIFD.Make: cam["make"].encode(),
        piexif.ImageIFD.Model: cam["model"].encode(),
        piexif.ImageIFD.Software: b"odm-aerial-photo-sfm/03_prepare_odm_inputs",
    }
    if dt:
        zeroth[piexif.ImageIFD.DateTime] = dt.encode()
    exif = {
        piexif.ExifIFD.ExifVersion: b"0230",
        piexif.ExifIFD.FocalLength: _rat(cam["focal_mm"], 100),
        piexif.ExifIFD.FocalLengthIn35mmFilm: focal35,
        piexif.ExifIFD.PixelXDimension: size[0],
        piexif.ExifIFD.PixelYDimension: size[1],
    }
    if dt:
        exif[piexif.ExifIFD.DateTimeOriginal] = dt.encode()
        exif[piexif.ExifIFD.DateTimeDigitized] = dt.encode()
    gps = {
        piexif.GPSIFD.GPSVersionID: (2, 3, 0, 0),
        piexif.GPSIFD.GPSLatitudeRef: b"N" if r.lat >= 0 else b"S",
        piexif.GPSIFD.GPSLatitude: _dms(r.lat),
        piexif.GPSIFD.GPSLongitudeRef: b"E" if r.lon >= 0 else b"W",
        piexif.GPSIFD.GPSLongitude: _dms(r.lon),
        piexif.GPSIFD.GPSAltitudeRef: 0 if alt_m >= 0 else 1,
        piexif.GPSIFD.GPSAltitude: _rat(abs(alt_m), 100),
    }
    return piexif.dump({"0th": zeroth, "Exif": exif, "GPS": gps})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--datasets-dir", type=Path, default=DATASETS_DIR)
    ap.add_argument("--camera", type=Path, default=REPO_ROOT / "config/cameras/dmc3_qv.json")
    ap.add_argument("--agl", type=float, default=None, help="above-ground height [m]; default: estimate")
    ap.add_argument("--ground-elev", type=float, default=100.0, help="mean ground elevation [m] added to AGL")
    ap.add_argument("--sidelap", type=float, default=0.30, help="assumed side overlap for AGL estimate")
    ap.add_argument("--with-yaw", action="store_true", help="write 9-column geo.txt with yaw/pitch/roll + accuracies")
    ap.add_argument("--horiz-acc", type=float, default=30.0)
    ap.add_argument("--vert-acc", type=float, default=100.0)
    ap.add_argument("--force", action="store_true", help="rewrite images/ even if present")
    args = ap.parse_args()

    proj = args.datasets_dir / args.project
    cam = json.loads(args.camera.read_text(encoding="utf-8"))
    recs = read_photos_csv(proj / "photos.csv")
    raw, images = proj / "raw", proj / "images"
    images.mkdir(parents=True, exist_ok=True)

    full_long, full_short = cam["full_size_px"]
    f_mm, px_um = cam["focal_mm"], cam["pixel_um_full"]
    sensor_long_mm = full_long * px_um / 1000.0
    focal35 = round(36.0 * f_mm / sensor_long_mm)

    along, across = spacing_stats(recs)
    if cam.get("long_side", "across_track") == "across_track":
        across_px, along_px = full_long, full_short
    else:
        across_px, along_px = full_short, full_long
    gsd_est = (across / (1.0 - args.sidelap)) / across_px           # m/px, full-res
    agl_est = gsd_est * f_mm / (px_um / 1000.0)                       # m
    fwd_overlap = 1.0 - along / (gsd_est * along_px)
    agl = args.agl if args.agl is not None else agl_est
    gsd_at_agl = agl * (px_um / 1000.0) / f_mm
    alt = args.ground_elev + agl

    print(f"camera: {cam['name']}  f={f_mm} mm  sensor long side {sensor_long_mm:.1f} mm  -> FocalLengthIn35mm {focal35}")
    print(f"spacing: along {along:.0f} m  across {across:.0f} m")
    print(f"estimate (sidelap {args.sidelap:.0%}): GSD_full {gsd_est:.3f} m/px  AGL {agl_est:.0f} m  forward overlap {fwd_overlap:.0%}")
    print(f"using AGL {agl:.0f} m (+ ground {args.ground_elev:.0f} m = GPSAltitude {alt:.0f} m); qv GSD ~ {gsd_at_agl*4:.2f} m/px")

    hd = headings(recs)
    diffs = [(r.rotation_deg - hd[r.file]) % 360 for r in recs if not math.isnan(hd[r.file])]
    if diffs:
        print(f"rotation_deg - heading: median {statistics.median(diffs):.1f} deg (viewer rotation vs. direction of travel)")

    geo_lines = ["EPSG:4326"]
    n_written = n_skipped = 0
    for r in recs:
        src, dst = raw / r.file, images / r.file
        if not src.exists():
            print(f"  missing raw: {r.file}", file=sys.stderr)
            continue
        if dst.exists() and not args.force:
            n_skipped += 1
        else:
            with Image.open(src) as im:
                size = im.size
            piexif.insert(build_exif(r, cam, alt, focal35, size), str(src), str(dst))
            n_written += 1
        if args.with_yaw:
            yaw = hd[r.file] if not math.isnan(hd[r.file]) else 0.0
            geo_lines.append(f"{r.file} {r.lon:.7f} {r.lat:.7f} {alt:.1f} {yaw:.1f} 0 0 {args.horiz_acc:g} {args.vert_acc:g}")
        else:
            geo_lines.append(f"{r.file} {r.lon:.7f} {r.lat:.7f} {alt:.1f}")

    (proj / "geo.txt").write_text("\n".join(geo_lines) + "\n", encoding="utf-8", newline="\n")
    info = {
        "project": args.project,
        "camera": cam["name"],
        "photos": len(recs),
        "focal_mm": f_mm,
        "focal35": focal35,
        "along_spacing_m": round(along, 1),
        "across_spacing_m": round(across, 1),
        "sidelap_assumed": args.sidelap,
        "gsd_full_est_m": round(gsd_est, 4),
        "forward_overlap_est": round(fwd_overlap, 3),
        "agl_est_m": round(agl_est, 1),
        "agl_used_m": round(agl, 1),
        "ground_elev_m": args.ground_elev,
        "gps_altitude_m": round(alt, 1),
        "qv_gsd_m": round(gsd_at_agl * 4, 3),
        "geo_txt_columns": 9 if args.with_yaw else 4,
    }
    (proj / "dataset_info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"images/: wrote {n_written}, kept {n_skipped}; geo.txt {len(geo_lines)-1} rows; dataset_info.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
