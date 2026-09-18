# odm-aerial-photo-sfm

国土地理院の空中写真から OpenDroneMap（SfM）で点群・DSM・正射画像を作り、
地理院標高タイル形式にして地理院公式 DSM と比較する検証リポジトリ。

パイロット: **令和6年能登半島地震 珠洲地区 1/2 撮影 垂直写真（133 枚, Leica DMC III, qv 版）**
→ 結果: [docs/results-suzu_0102.md](docs/results-suzu_0102.md)（GCP なし、地理院 1mDSM との差 RMSE 4.95 m @z15、高さオフセット補正後）

- [docs/design.md](docs/design.md) — 設計書（データ諸元・処理フロー・パラメータ根拠）
- [docs/notes.md](docs/notes.md) — 調査メモ（参照記事・地理院データの所在・2022→現在の差分）

## 処理フロー

```
01_fetch_metadata.py   地理院地図 GeoJSON → datasets/<proj>/photos.csv（写真URL・主点座標・コース・撮影時刻）
02_fetch_photos.py     qv JPEG を datasets/<proj>/raw/ へ（1 req/s, 再開可）
03_prepare_odm_inputs.py  EXIF（GPS・焦点距離・カメラ名）を注入して images/ へ、geo.txt・dataset_info.json を生成
04_run_odm.ps1         docker run opendronemap/odm:gpu … --dsm --orthophoto
05_dsm_to_gsi_tiles.py odm_dem/dsm.tif → EPSG:3857 → 地理院標高タイル PNG（output/<proj>/dsm_tiles/{z}/{x}/{y}.png）
06_compare_dsm.py      地理院 1mDSM タイルと画素単位で差分 → docs/results-*.md
07_ortho_to_xyz_tiles.py  odm_orthophoto.tif → XYZ PNG タイル（output/<proj>/ortho_tiles/）
viewer/index.html      MapLibre で自作 DSM と地理院 1mDSM を terrain/陰影として切替表示
```

## 環境

- Windows 11 / Docker Desktop (WSL2) / NVIDIA GPU（動作確認: RTX 4060 8GB, Ryzen 7 5700X, RAM 64GB）
- Python 3.12: `pip install -r requirements.txt`（requests, Pillow, piexif, numpy, rasterio）
- `%USERPROFILE%\.wslconfig` に `memory=48GB` / `processors=14` / `swap=16GB` を設定（Docker Desktop 再起動で反映）。珠洲 133 枚は既定の 32GB でも完走した

```powershell
docker pull opendronemap/odm:gpu     # 動作確認: ODM 3.6.2 (image c6ecdec77640, 9.4 GB)
```

## 実行手順（珠洲 1/2）

```powershell
$env:PYTHONUTF8 = "1"
python scripts/01_fetch_metadata.py --layer 20240102noto_suzu_0102suichoku --project suzu_0102
python scripts/02_fetch_photos.py --project suzu_0102
python scripts/03_prepare_odm_inputs.py --project suzu_0102 --camera config/cameras/dmc3_qv.json
.\scripts\04_run_odm.ps1 -Project suzu_0102            # ログ: datasets/suzu_0102/odm_log.txt（珠洲: 約 40 分）
python scripts/05_dsm_to_gsi_tiles.py --project suzu_0102
python scripts/06_compare_dsm.py --project suzu_0102 --zoom 15   # → 中央値オフセットを確認
python scripts/05_dsm_to_gsi_tiles.py --project suzu_0102 --z-offset 463.67   # オフセット分を補正して再タイル化
python scripts/07_ortho_to_xyz_tiles.py --project suzu_0102

# ビューア（リポジトリルートで静的配信し viewer/ を開く）
python -m http.server 8000
# → http://localhost:8000/viewer/
```

他地区は `--layer` と `--project` を変え、カメラ定義（`config/cameras/`）を UCE/UCO 用に追加する。

## 公開ビューア（GitHub Pages）

https://shiwaku.github.io/odm-aerial-photo-sfm/viewer/

タイル一式（725 MB）は Pages に載せられないため、`gh-pages` ブランチには DSM z10–15（地理院 1mDSM の配信範囲と同じ）と
正射画像 z10–16 に絞ったコピー（約 155 MB）を置く。ビューアは各 `metadata.json` の `maxzoom` を読むので、
ローカル（z17 まで）と Pages（縮小版）で同じ HTML が動く。

```powershell
python scripts/08_publish_pages.py --project suzu_0102 --push   # gh-pages を orphan 1 コミットで force-push
```

## 入力データについて

- 垂直写真の所在・諸元は [docs/notes.md §7](docs/notes.md)。写真は EXIF を持たないため、03 で
  主点座標（GeoJSON）・焦点距離 92 mm・35mm 換算 33 mm・推定 GPS 高度を書き込む
- 対地高度はコース間隔（≈3150 m）と側方オーバーラップ 30% の仮定から ≈4120 m と推定
  （原寸 GSD 0.175 m、qv で 0.70 m/px）。`--agl` / `--ground-elev` で上書き可
- 実測では側方オーバーラップ ≈37%・対地高度 ≈4590 m で、DSM が一律 −464 m 低く出た。
  水平位置・スケール・形状には影響しないので、06 で求めた中央値オフセットを 05 の `--z-offset` で補正する
  （次回は `03 --agl 4587` で最初から合わせる）
- GCP は使っていない。主点座標が位置とスケールを決めるので、Qiita 記事（位置情報なしの写真）とは前提が異なる
- 出典: 国土地理院「令和6年能登半島地震 空中写真」（国土地理院コンテンツ利用規約に従う）

## ディレクトリ

```
datasets/<proj>/   photos.csv, raw/, images/, geo.txt, dataset_info.json, ODM 出力（git 管理外）
output/<proj>/     dsm_tiles/（地理院標高タイル PNG）, ortho_tiles/（XYZ PNG）, 各 metadata.json（git 管理外）
config/cameras/    カメラ物理パラメータ（EXIF 注入用）
scripts/           01〜07 + common.py
viewer/            MapLibre ビューア
docs/              設計書・メモ・結果
```
