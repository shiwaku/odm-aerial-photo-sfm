"""[F] Compare our GSI-format DSM tiles against a GSI reference elevation layer, pixel by pixel.

Usage:
  python scripts/06_compare_dsm.py --project suzu_0102 --zoom 15
      [--ref-layer 20240102noto_1mDSM] [--tiles output/suzu_0102/dsm_tiles]
      [--interval 0.2] [--out docs/results-suzu_0102-compare.md]

For every tile of ours at --zoom, the matching reference tile is fetched from
https://maps.gsi.go.jp/xyz/<ref-layer>/{z}/{x}/{y}.png (cached under output/cache/),
both are decoded (GSI PNG elevation encoding), and the difference
    d = ours - reference
is accumulated over pixels valid in both. Reported:
  n, mean, median, std, RMSE, p5/p95, and the same after removing the median offset
  (our absolute height is only as good as the assumed GPS altitude, so the
  offset-free numbers describe the shape agreement).
A histogram of d is written as CSV next to the markdown report.

Reference layers of interest:
  20240102noto_1mDSM   GSI SfM DSM (post-quake), z up to 17
  dem5a_png / dem5b_png  基盤地図情報 DEM5 (pre-quake ground), z up to 15
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO_ROOT, USER_AGENT  # noqa: E402

GSI_XYZ = "https://maps.gsi.go.jp/xyz/{layer}/{z}/{x}/{y}.png"


def decode_gsi(png_bytes: bytes) -> tuple[np.ndarray, np.ndarray]:
    a = np.asarray(Image.open(io.BytesIO(png_bytes)).convert("RGB")).astype(np.int64)
    invalid = (a[..., 0] == 128) & (a[..., 1] == 0) & (a[..., 2] == 0)
    v = (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]
    v = np.where(v >= (1 << 23), v - (1 << 24), v)
    return v.astype(np.float64) * 0.01, ~invalid


def fetch_ref(sess: requests.Session, layer: str, z: int, x: int, y: int, cache: Path,
              interval: float) -> bytes | None:
    p = cache / layer / str(z) / str(x) / f"{y}.png"
    if p.exists():
        return p.read_bytes() if p.stat().st_size > 0 else None
    p.parent.mkdir(parents=True, exist_ok=True)
    r = sess.get(GSI_XYZ.format(layer=layer, z=z, x=x, y=y), timeout=30)
    time.sleep(interval)
    if r.status_code == 404:
        p.write_bytes(b"")  # remember the miss
        return None
    r.raise_for_status()
    p.write_bytes(r.content)
    return r.content


def stats(d: np.ndarray) -> dict:
    if d.size == 0:
        return {"n": 0}
    med = float(np.median(d))
    d0 = d - med
    return {
        "n": int(d.size),
        "mean": float(d.mean()),
        "median": med,
        "std": float(d.std()),
        "rmse": float(np.sqrt(np.mean(d ** 2))),
        "p5": float(np.percentile(d, 5)),
        "p95": float(np.percentile(d, 95)),
        "mad": float(np.median(np.abs(d0))),
        "rmse_offset_removed": float(np.sqrt(np.mean(d0 ** 2))),
        "p5_offset_removed": float(np.percentile(d0, 5)),
        "p95_offset_removed": float(np.percentile(d0, 95)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--tiles", type=Path, default=None, help="default output/<proj>/dsm_tiles")
    ap.add_argument("--zoom", type=int, default=15)
    ap.add_argument("--ref-layer", default="20240102noto_1mDSM")
    ap.add_argument("--interval", type=float, default=0.2)
    ap.add_argument("--cache", type=Path, default=REPO_ROOT / "output" / "cache")
    ap.add_argument("--out", type=Path, default=None, help="markdown report path")
    ap.add_argument("--clip", type=float, default=200.0, help="ignore |d| above this [m] as gross outliers")
    args = ap.parse_args()

    tiles = args.tiles or (REPO_ROOT / "output" / args.project / "dsm_tiles")
    out_md = args.out or (REPO_ROOT / "docs" / f"results-{args.project}-vs-{args.ref_layer}-z{args.zoom}.md")
    zdir = tiles / str(args.zoom)
    if not zdir.exists():
        print(f"no tiles at {zdir}", file=sys.stderr)
        return 2

    sess = requests.Session()
    sess.headers["User-Agent"] = USER_AGENT
    diffs: list[np.ndarray] = []
    per_tile = []
    n_tiles = n_ref_missing = 0
    for xdir in sorted(zdir.iterdir(), key=lambda p: int(p.name)):
        for ypng in sorted(xdir.iterdir(), key=lambda p: int(p.stem)):
            x, y = int(xdir.name), int(ypng.stem)
            n_tiles += 1
            ref = fetch_ref(sess, args.ref_layer, args.zoom, x, y, args.cache, args.interval)
            if ref is None:
                n_ref_missing += 1
                continue
            h_ours, v_ours = decode_gsi(ypng.read_bytes())
            h_ref, v_ref = decode_gsi(ref)
            both = v_ours & v_ref
            if not both.any():
                continue
            d = h_ours[both] - h_ref[both]
            d = d[np.abs(d) <= args.clip]
            if d.size:
                diffs.append(d)
                per_tile.append({"x": x, "y": y, "n": int(d.size), "median": float(np.median(d)),
                                 "rmse": float(np.sqrt(np.mean(d ** 2)))})
    d_all = np.concatenate(diffs) if diffs else np.empty(0)
    s = stats(d_all)
    print(json.dumps(s, indent=2))

    # histogram CSV
    out_md.parent.mkdir(parents=True, exist_ok=True)
    hist_csv = out_md.with_suffix(".hist.csv")
    if d_all.size:
        edges = np.arange(-50, 50.5, 0.5)
        counts, _ = np.histogram(np.clip(d_all, -50, 50), bins=edges)
        with hist_csv.open("w", encoding="utf-8") as f:
            f.write("bin_lo_m,bin_hi_m,count\n")
            for lo, hi, c in zip(edges[:-1], edges[1:], counts):
                f.write(f"{lo:.1f},{hi:.1f},{c}\n")

    res = 2 * 20037508.342789244 / (256 * 2 ** args.zoom)
    lines = [
        f"# DSM 比較: {args.project} (ODM) vs `{args.ref_layer}` @ z{args.zoom}",
        "",
        f"- 生成: {time.strftime('%Y-%m-%d %H:%M')}",
        f"- 比較解像度: z{args.zoom} ≈ {res:.2f} m/px（赤道）",
        f"- 自作タイル {n_tiles} 枚、参照側なし {n_ref_missing} 枚、有効画素 {s.get('n', 0):,}",
        f"- 外れ値クリップ: |d| > {args.clip:g} m を除外",
        "",
        "| 指標 | 生の差 d = 自作 − 参照 [m] | 中央値オフセット除去後 [m] |",
        "|---|---|---|",
    ]
    if s.get("n"):
        lines += [
            f"| 平均 | {s['mean']:+.2f} | 0.00 |",
            f"| 中央値 | {s['median']:+.2f} | 0.00 |",
            f"| 標準偏差 | {s['std']:.2f} | {s['std']:.2f} |",
            f"| RMSE | {s['rmse']:.2f} | {s['rmse_offset_removed']:.2f} |",
            f"| MAD | – | {s['mad']:.2f} |",
            f"| 5% / 95% | {s['p5']:+.2f} / {s['p95']:+.2f} | {s['p5_offset_removed']:+.2f} / {s['p95_offset_removed']:+.2f} |",
            "",
            f"ヒストグラム: `{hist_csv.name}`（0.5 m ビン、±50 m）",
            "",
            "## タイル別（RMSE 上位 10）",
            "",
            "| x | y | n | median | RMSE |",
            "|---|---|---|---|---|",
        ]
        for t in sorted(per_tile, key=lambda t: -t["rmse"])[:10]:
            lines.append(f"| {t['x']} | {t['y']} | {t['n']} | {t['median']:+.2f} | {t['rmse']:.2f} |")
    else:
        lines.append("| (有効画素なし) | | |")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_md.with_suffix(".tiles.json").write_text(
        json.dumps({"zoom": args.zoom, "ref_layer": args.ref_layer, "stats": s, "tiles": per_tile}, indent=1),
        encoding="utf-8")
    print(f"wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
