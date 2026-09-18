"""[G] Build (and optionally push) the GitHub Pages site: viewer + a zoom-limited copy of the tiles.

Usage:
  python scripts/08_publish_pages.py --project suzu_0102 [--dsm-maxzoom 15] [--ortho-maxzoom 16]
      [--out <dir>] [--push] [--branch gh-pages]

Full tile sets are too big for Pages (suzu_0102: DSM 293 MB, ortho 432 MB, mostly z16-17), so
this copies only z <= the given max zooms (defaults: DSM z15 = the range GSI serves its 1mDSM at,
ortho z16) and rewrites each metadata.json so the viewer picks up the reduced maxzoom.

Site layout (relative paths in viewer/index.html keep working):
  /index.html                     -> redirect to viewer/
  /viewer/index.html
  /output/<proj>/dsm_tiles/...    z10..dsm-maxzoom + metadata.json
  /output/<proj>/ortho_tiles/...  z10..ortho-maxzoom + metadata.json

--push commits the built tree as a single-commit orphan `gh-pages` branch (history is not kept:
tiles are generated artefacts) and force-pushes it to origin.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO_ROOT  # noqa: E402

REDIRECT = """<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=viewer/"><title>odm-aerial-photo-sfm</title></head>
<body><a href="viewer/">viewer/</a></body></html>
"""


def copy_tiles(src: Path, dst: Path, maxzoom: int) -> tuple[int, int]:
    n = size = 0
    meta = json.loads((src / "metadata.json").read_text(encoding="utf-8"))
    for zdir in sorted(src.iterdir(), key=lambda p: (not p.name.isdigit(), p.name)):
        if not zdir.is_dir() or not zdir.name.isdigit() or int(zdir.name) > maxzoom:
            continue
        for png in zdir.rglob("*.png"):
            rel = png.relative_to(src)
            out = dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(png, out)
            n += 1
            size += png.stat().st_size
    meta["maxzoom"] = min(meta.get("maxzoom", maxzoom), maxzoom)
    meta["tiles_per_zoom"] = {z: c for z, c in meta.get("tiles_per_zoom", {}).items() if int(z) <= maxzoom}
    meta["published"] = "github-pages (zoom-limited copy)"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return n, size


def run(cmd: list[str], cwd: Path) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--dsm-maxzoom", type=int, default=15)
    ap.add_argument("--ortho-maxzoom", type=int, default=16)
    ap.add_argument("--out", type=Path, default=None, help="build directory (default: temp dir)")
    ap.add_argument("--push", action="store_true", help="commit as orphan branch and force-push to origin")
    ap.add_argument("--branch", default="gh-pages")
    args = ap.parse_args()

    out = args.out or Path(tempfile.mkdtemp(prefix="gh-pages-"))
    if out.exists():
        for child in out.iterdir():
            if child.name == ".git":
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)

    (out / "index.html").write_text(REDIRECT, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    shutil.copytree(REPO_ROOT / "viewer", out / "viewer", dirs_exist_ok=True)

    total = 0
    for kind, mz in (("dsm_tiles", args.dsm_maxzoom), ("ortho_tiles", args.ortho_maxzoom)):
        src = REPO_ROOT / "output" / args.project / kind
        if not (src / "metadata.json").exists():
            print(f"skip {kind}: {src} has no metadata.json")
            continue
        n, size = copy_tiles(src, out / "output" / args.project / kind, mz)
        total += size
        print(f"{kind}: {n} tiles up to z{mz}, {size/1e6:.1f} MB")
    print(f"site built at {out} ({total/1e6:.1f} MB of tiles)")

    if args.push:
        remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=REPO_ROOT,
                                capture_output=True, text=True, check=True).stdout.strip()
        run(["git", "init", "-q", "-b", args.branch], out)
        run(["git", "add", "-A"], out)
        run(["git", "commit", "-q", "-m", f"pages: {args.project} viewer + tiles (dsm z<={args.dsm_maxzoom}, "
                                          f"ortho z<={args.ortho_maxzoom})"], out)
        run(["git", "push", "-f", remote, f"{args.branch}:{args.branch}"], out)
        print(f"pushed {args.branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
