"""[E'] Convert the ODM orthophoto (RGBA GeoTIFF) into plain XYZ PNG tiles for the viewer.

Usage:
  python scripts/07_ortho_to_xyz_tiles.py --project suzu_0102
      [--ortho datasets/suzu_0102/odm_orthophoto/odm_orthophoto.tif] [--minzoom 10] [--maxzoom 17]
      [--out output/suzu_0102/ortho_tiles]

Same tiling scheme as 05 (EPSG:3857, 256px, lower zooms by 2x2 average), but for
RGB + alpha. Transparent where the orthophoto has no data.
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
ORIGIN = 20037508.342789244


def zoom_res(z: int) -> float:
    return 2 * ORIGIN / (TILE * 2 ** z)


def warp_rgba(src_path: Path, res: float) -> tuple[np.ndarray, rasterio.Affine]:
    with rasterio.open(src_path) as src:
        minx, miny, maxx, maxy = transform_bounds(src.crs, "EPSG:3857", *src.bounds, densify_pts=21)
        tile_m = res * TILE
        tx0 = math.floor((minx + ORIGIN) / tile_m)
        ty0 = math.floor((ORIGIN - maxy) / tile_m)
        ox = -ORIGIN + tx0 * tile_m
        oy = ORIGIN - ty0 * tile_m
        width = math.ceil((maxx - ox) / tile_m) * TILE
        height = math.ceil((oy - miny) / tile_m) * TILE
        transform = rasterio.Affine(res, 0, ox, 0, -res, oy)
        nb = src.count
        bands = [1, 2, 3] if nb >= 3 else [1, 1, 1]
        rgba = np.zeros((4, height, width), dtype=np.uint8)
        for i, b in enumerate(bands):
            reproject(source=rasterio.band(src, b), destination=rgba[i],
                      src_transform=src.transform, src_crs=src.crs,
                      dst_transform=transform, dst_crs="EPSG:3857",
                      resampling=Resampling.bilinear, num_threads=4)
        if nb >= 4:
            reproject(source=rasterio.band(src, 4), destination=rgba[3],
                      src_transform=src.transform, src_crs=src.crs,
                      dst_transform=transform, dst_crs="EPSG:3857",
                      resampling=Resampling.nearest, num_threads=4)
        else:
            mask = np.zeros((height, width), dtype=np.uint8)
            reproject(source=src.read_masks(1), destination=mask,
                      src_transform=src.transform, src_crs=src.crs,
                      dst_transform=transform, dst_crs="EPSG:3857",
                      resampling=Resampling.nearest, num_threads=4)
            rgba[3] = mask
    return np.moveaxis(rgba, 0, -1), transform  # H, W, 4


def downsample(img: np.ndarray) -> np.ndarray:
    """2x2 alpha-weighted mean; input dims even."""
    H, W, _ = img.shape
    a = img[..., 3].astype(np.float32).reshape(H // 2, 2, W // 2, 2)
    rgb = img[..., :3].astype(np.float32).reshape(H // 2, 2, W // 2, 2, 3)
    wsum = a.sum(axis=(1, 3))
    out = np.zeros((H // 2, W // 2, 4), dtype=np.uint8)
    num = (rgb * a[..., None]).sum(axis=(1, 3))
    out[..., :3] = np.where(wsum[..., None] > 0, num / np.maximum(wsum, 1)[..., None], 0).astype(np.uint8)
    out[..., 3] = (wsum / 4).astype(np.uint8)
    return out


def align_for_parent(img: np.ndarray, transform: rasterio.Affine):
    res = transform.a
    tx0 = int(round((transform.c + ORIGIN) / (res * TILE)))
    ty0 = int(round((ORIGIN - transform.f) / (res * TILE)))
    padx, pady = (tx0 % 2) * TILE, (ty0 % 2) * TILE
    H, W, _ = img.shape
    newH = math.ceil((H + pady) / (2 * TILE)) * 2 * TILE
    newW = math.ceil((W + padx) / (2 * TILE)) * 2 * TILE
    if (padx, pady) == (0, 0) and (newH, newW) == (H, W):
        return img, transform
    out = np.zeros((newH, newW, 4), dtype=np.uint8)
    out[pady:pady + H, padx:padx + W] = img
    t = rasterio.Affine(res, 0, transform.c - padx * res, 0, -res, transform.f + pady * res)
    return out, t


def write_tiles(img: np.ndarray, transform: rasterio.Affine, z: int, out: Path) -> int:
    res = transform.a
    x0 = int(round((transform.c + ORIGIN) / (res * TILE)))
    y0 = int(round((ORIGIN - transform.f) / (res * TILE)))
    ny, nx = img.shape[0] // TILE, img.shape[1] // TILE
    n = 0
    for ty in range(ny):
        for tx in range(nx):
            t = img[ty * TILE:(ty + 1) * TILE, tx * TILE:(tx + 1) * TILE]
            if not t[..., 3].any():
                continue
            p = out / str(z) / str(x0 + tx) / f"{y0 + ty}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(t, "RGBA").save(p, optimize=True)
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--datasets-dir", type=Path, default=DATASETS_DIR)
    ap.add_argument("--ortho", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--minzoom", type=int, default=10)
    ap.add_argument("--maxzoom", type=int, default=17)
    args = ap.parse_args()

    ortho = args.ortho or (args.datasets_dir / args.project / "odm_orthophoto" / "odm_orthophoto.tif")
    out = args.out or (REPO_ROOT / "output" / args.project / "ortho_tiles")
    out.mkdir(parents=True, exist_ok=True)

    res = zoom_res(args.maxzoom)
    print(f"warping {ortho} -> EPSG:3857 @ {res:.3f} m/px (z{args.maxzoom})")
    img, transform = warp_rgba(ortho, res)
    print(f"raster {img.shape[1]}x{img.shape[0]} px, opaque {np.mean(img[..., 3] > 0):.1%}")

    counts = {}
    for z in range(args.maxzoom, args.minzoom - 1, -1):
        counts[z] = write_tiles(img, transform, z, out)
        print(f"  z{z}: {counts[z]} tiles")
        if z > args.minzoom:
            img, transform = align_for_parent(img, transform)
            img = downsample(img)
            transform = rasterio.Affine(transform.a * 2, 0, transform.c, 0, transform.e * 2, transform.f)

    with rasterio.open(ortho) as src:
        lonlat = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
    meta = {"name": f"{args.project} orthophoto (ODM)", "tile_url": "{z}/{x}/{y}.png",
            "minzoom": args.minzoom, "maxzoom": args.maxzoom,
            "bounds_4326": [round(v, 6) for v in lonlat], "tiles_per_zoom": counts,
            "attribution": "国土地理院 空中写真（令和6年能登半島地震）を OpenDroneMap で処理"}
    (out / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {sum(counts.values())} tiles -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
