"""[E] Convert an ODM DSM GeoTIFF into GSI elevation PNG tiles (地理院標高タイル形式).

Usage:
  python scripts/05_dsm_to_gsi_tiles.py --project suzu_0102 [--dsm datasets/suzu_0102/odm_dem/dsm.tif]
      [--minzoom 10] [--maxzoom 17] [--out output/suzu_0102/dsm_tiles]

Encoding (GSI PNG elevation tile, 256x256, EPSG:3857):
  x = round(h / 0.01);  if x < 0: x += 2**24
  R = x >> 16,  G = (x >> 8) & 255,  B = x & 255
  invalid (nodata) = (128, 0, 0)

Pipeline:
  1. reproject dsm.tif (UTM) -> EPSG:3857 at the native resolution of --maxzoom (bilinear)
  2. cut 256px tiles for maxzoom directly from the warped raster
  3. build lower zooms by 2x2 averaging of valid children (nodata-aware)
  4. write metadata.json (bounds, zooms, attribution) for the viewer
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS_DIR, REPO_ROOT  # noqa: E402

TILE = 256
ORIGIN = 20037508.342789244  # half the EPSG:3857 world width
INVALID = np.array([128, 0, 0], dtype=np.uint8)


def zoom_res(z: int) -> float:
    return 2 * ORIGIN / (TILE * 2 ** z)


def tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    r = zoom_res(z) * TILE
    minx = -ORIGIN + x * r
    maxy = ORIGIN - y * r
    return minx, maxy - r, minx + r, maxy


def encode_gsi(h: np.ndarray, valid: np.ndarray) -> np.ndarray:
    x = np.rint(np.nan_to_num(h, nan=0.0) / 0.01).astype(np.int64)
    x = np.where(x < 0, x + (1 << 24), x)
    x = np.clip(x, 0, (1 << 24) - 1).astype(np.uint32)
    rgb = np.empty((*h.shape, 3), dtype=np.uint8)
    rgb[..., 0] = (x >> 16) & 255
    rgb[..., 1] = (x >> 8) & 255
    rgb[..., 2] = x & 255
    rgb[~valid] = INVALID
    return rgb


def warp_to_3857(src_path: Path, res: float) -> tuple[np.ndarray, np.ndarray, rasterio.Affine]:
    with rasterio.open(src_path) as src:
        nodata = src.nodata
        minx, miny, maxx, maxy = src_bounds_3857(src)
        # snap the origin to the pixel grid at this resolution so tile cutting is an integer slice
        ox = math.floor((minx + ORIGIN) / res) * res - ORIGIN
        oy = ORIGIN - math.floor((ORIGIN - maxy) / res) * res
        transform = rasterio.Affine(res, 0, ox, 0, -res, oy)
        width = math.ceil((maxx - ox) / res)
        height = math.ceil((oy - miny) / res)
        dst = np.full((height, width), np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1), destination=dst,
            src_transform=src.transform, src_crs=src.crs, src_nodata=nodata,
            dst_transform=transform, dst_crs="EPSG:3857", dst_nodata=np.nan,
            resampling=Resampling.bilinear, num_threads=4,
        )
    valid = np.isfinite(dst)
    return dst, valid, transform


def src_bounds_3857(src) -> tuple[float, float, float, float]:
    return transform_bounds(src.crs, "EPSG:3857", *src.bounds, densify_pts=21)


def downsample(h: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """2x2 nodata-aware mean. Arrays must have even dimensions."""
    hh = np.where(valid, h, 0.0).reshape(h.shape[0] // 2, 2, h.shape[1] // 2, 2)
    vv = valid.reshape(valid.shape[0] // 2, 2, valid.shape[1] // 2, 2)
    s = hh.sum(axis=(1, 3))
    n = vv.sum(axis=(1, 3))
    out = np.where(n > 0, s / np.maximum(n, 1), np.nan).astype(np.float32)
    return out, n > 0


def write_tiles(h: np.ndarray, valid: np.ndarray, transform: rasterio.Affine, z: int, out: Path) -> int:
    res = transform.a
    x0 = int(round((transform.c + ORIGIN) / (res * TILE)))
    y0 = int(round((ORIGIN - transform.f) / (res * TILE)))
    ny, nx = h.shape[0] // TILE, h.shape[1] // TILE
    n = 0
    for ty in range(ny):
        for tx in range(nx):
            sl = (slice(ty * TILE, (ty + 1) * TILE), slice(tx * TILE, (tx + 1) * TILE))
            v = valid[sl]
            if not v.any():
                continue
            rgb = encode_gsi(h[sl], v)
            p = out / str(z) / str(x0 + tx) / f"{y0 + ty}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rgb, "RGB").save(p, optimize=True)
            n += 1
    return n


def pad_to_tiles(h: np.ndarray, valid: np.ndarray, transform: rasterio.Affine):
    """Pad so the raster starts on a tile corner and its size is a multiple of TILE."""
    res = transform.a
    tile_m = res * TILE
    tx0 = math.floor((transform.c + ORIGIN) / tile_m)
    ty0 = math.floor((ORIGIN - transform.f) / tile_m)
    left = int(round(((transform.c + ORIGIN) - tx0 * tile_m) / res))
    top = int(round(((ORIGIN - transform.f) - ty0 * tile_m) / res))
    H, W = h.shape
    newH = math.ceil((top + H) / TILE) * TILE
    newW = math.ceil((left + W) / TILE) * TILE
    ph = np.full((newH, newW), np.nan, dtype=np.float32)
    pv = np.zeros((newH, newW), dtype=bool)
    ph[top:top + H, left:left + W] = h
    pv[top:top + H, left:left + W] = valid
    t = rasterio.Affine(res, 0, -ORIGIN + tx0 * tile_m, 0, -res, ORIGIN - ty0 * tile_m)
    return ph, pv, t


def align_for_parent(h: np.ndarray, valid: np.ndarray, transform: rasterio.Affine):
    """Pad so that (a) the top-left tile index is even and (b) dims are multiples of 2*TILE,
    so a 2x2 downsample lands exactly on the parent zoom's tile grid."""
    res = transform.a
    tx0 = int(round((transform.c + ORIGIN) / (res * TILE)))
    ty0 = int(round((ORIGIN - transform.f) / (res * TILE)))
    padx, pady = (tx0 % 2) * TILE, (ty0 % 2) * TILE
    H, W = h.shape
    newH = math.ceil((H + pady) / (2 * TILE)) * 2 * TILE
    newW = math.ceil((W + padx) / (2 * TILE)) * 2 * TILE
    if (padx, pady) == (0, 0) and (newH, newW) == (H, W):
        return h, valid, transform
    ph = np.full((newH, newW), np.nan, dtype=np.float32)
    pv = np.zeros((newH, newW), dtype=bool)
    ph[pady:pady + H, padx:padx + W] = h
    pv[pady:pady + H, padx:padx + W] = valid
    t = rasterio.Affine(res, 0, transform.c - padx * res, 0, -res, transform.f + pady * res)
    return ph, pv, t


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--datasets-dir", type=Path, default=DATASETS_DIR)
    ap.add_argument("--dsm", type=Path, default=None, help="default datasets/<proj>/odm_dem/dsm.tif")
    ap.add_argument("--out", type=Path, default=None, help="default output/<proj>/dsm_tiles")
    ap.add_argument("--minzoom", type=int, default=10)
    ap.add_argument("--maxzoom", type=int, default=17)
    ap.add_argument("--name", default=None, help="label for metadata.json")
    ap.add_argument("--z-offset", type=float, default=0.0,
                    help="add this many metres to every height (e.g. the median offset vs a reference DSM "
                         "from 06_compare_dsm.py; our absolute Z depends on the assumed GPS altitude)")
    args = ap.parse_args()

    dsm = args.dsm or (args.datasets_dir / args.project / "odm_dem" / "dsm.tif")
    out = args.out or (REPO_ROOT / "output" / args.project / "dsm_tiles")
    out.mkdir(parents=True, exist_ok=True)

    res = zoom_res(args.maxzoom)
    print(f"warping {dsm} -> EPSG:3857 @ {res:.3f} m/px (z{args.maxzoom})")
    h, valid, transform = warp_to_3857(dsm, res)
    h, valid, transform = pad_to_tiles(h, valid, transform)
    if args.z_offset:
        h = np.where(valid, h + np.float32(args.z_offset), h)
        print(f"applied z-offset {args.z_offset:+.2f} m")
    print(f"raster {h.shape[1]}x{h.shape[0]} px, valid {valid.mean():.1%}, "
          f"h range {np.nanmin(h):.1f}..{np.nanmax(h):.1f} m")

    with rasterio.open(dsm) as src:
        b = src_bounds_3857(src)
    with rasterio.open(dsm) as src:
        lonlat = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)

    counts = {}
    for z in range(args.maxzoom, args.minzoom - 1, -1):
        counts[z] = write_tiles(h, valid, transform, z, out)
        print(f"  z{z}: {counts[z]} tiles")
        if z > args.minzoom:
            h, valid, transform = align_for_parent(h, valid, transform)
            h, valid = downsample(h, valid)
            transform = rasterio.Affine(transform.a * 2, 0, transform.c, 0, transform.e * 2, transform.f)

    meta = {
        "name": args.name or f"{args.project} DSM (ODM)",
        "format": "gsi-elevation-png",
        "tile_url": "{z}/{x}/{y}.png",
        "minzoom": args.minzoom,
        "maxzoom": args.maxzoom,
        "bounds_4326": [round(v, 6) for v in lonlat],
        "bounds_3857": [round(v, 1) for v in b],
        "tiles_per_zoom": counts,
        "z_offset_m": args.z_offset,
        "source_dsm": str(dsm.relative_to(REPO_ROOT)) if dsm.is_relative_to(REPO_ROOT) else str(dsm),
        "attribution": "国土地理院 空中写真（令和6年能登半島地震）を OpenDroneMap で処理",
    }
    (out / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {sum(counts.values())} tiles -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
