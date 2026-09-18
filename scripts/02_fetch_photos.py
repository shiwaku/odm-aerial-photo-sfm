"""[B] Download the qv JPEGs listed in photos.csv into datasets/<proj>/raw/.

Usage:
  python scripts/02_fetch_photos.py --project suzu_0102 [--interval 1.0] [--expect-size 3648x6432]

- 1 request/second by default (GSI terms: be gentle with bulk download)
- resumable: a file that already exists and opens as a JPEG of the expected size is skipped
- 3 retries with back-off per file
- raw/ keeps the untouched originals; 03_prepare_odm_inputs.py writes EXIF-injected copies to images/
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS_DIR, USER_AGENT, read_photos_csv  # noqa: E402


def check_jpeg(path: Path, expect: tuple[int, int] | None) -> bool:
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            size = im.size
    except Exception:
        return False
    if expect and size != expect:
        print(f"  WARNING {path.name}: size {size} != expected {expect}", file=sys.stderr)
    return True


def download(sess: requests.Session, url: str, dst: Path, retries: int = 3) -> bool:
    tmp = dst.with_suffix(".part")
    for attempt in range(1, retries + 1):
        try:
            with sess.get(url, stream=True, timeout=(10, 120)) as r:
                r.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)
            tmp.replace(dst)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"  retry {attempt}/{retries} {dst.name}: {e}", file=sys.stderr)
            time.sleep(2 * attempt)
    tmp.unlink(missing_ok=True)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--datasets-dir", type=Path, default=DATASETS_DIR)
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("--expect-size", default="3648x6432", help="WxH to warn on, or 'none'")
    ap.add_argument("--limit", type=int, default=0, help="download at most N files (0 = all)")
    args = ap.parse_args()

    proj = args.datasets_dir / args.project
    recs = read_photos_csv(proj / "photos.csv")
    raw = proj / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    expect = None if args.expect_size.lower() == "none" else tuple(int(x) for x in args.expect_size.lower().split("x"))

    sess = requests.Session()
    sess.headers["User-Agent"] = USER_AGENT
    done = skipped = failed = 0
    t0 = time.time()
    for i, r in enumerate(recs, 1):
        if args.limit and done >= args.limit:
            break
        dst = raw / r.file
        if dst.exists() and check_jpeg(dst, expect):
            skipped += 1
            continue
        ok = download(sess, r.url, dst)
        if ok and check_jpeg(dst, expect):
            done += 1
            print(f"[{i:3d}/{len(recs)}] {r.file}  {dst.stat().st_size/1e6:.2f} MB")
        else:
            failed += 1
            print(f"[{i:3d}/{len(recs)}] {r.file}  FAILED", file=sys.stderr)
        time.sleep(args.interval)
    dt = time.time() - t0
    print(f"downloaded {done}, skipped {skipped}, failed {failed} in {dt:.0f}s -> {raw}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
