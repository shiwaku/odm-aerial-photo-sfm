# 設計書: 能登半島地震 垂直写真 → ODM → DSM タイル

作成: 2026-09-18 / 状態: ドラフト（未着手）

## 1. 目的

国土地理院が公開している令和6年能登半島地震の**垂直写真（単写真）**を入力に、OpenDroneMap（ODM）で
点群・DSM・正射画像を生成し、DSM を**地理院標高タイル形式の PNG タイル**にして、
地理院公式の SfM DSM（`20240102noto_1mDSM`）と同じビューア上で比較できる状態にする。

- 地理院が災害直後に行った「空中写真 → SfM → DSM」を、公開データと OSS だけで再現する
- 地理院 DSM との差（範囲・分解能・高さの偏差）を定量的に把握する
- 手順をスクリプト化し、他地区・他日・他災害に横展開できる形にする

## 2. スコープ

| | 含む | 含まない |
|---|---|---|
| 入力 | 地理院公開の垂直写真 qv 版（3648×6432） | 原寸写真（未公開）、閲覧サービスの有償高解像度 |
| 処理 | ODM による SfM/MVS、DSM、正射画像、点群 | 手動 GCP 測設（Phase 2 で検討） |
| 出力 | DSM GeoTIFF、地理院標高タイル PNG、比較用 MapLibre ビューア | 3D Tiles 配信（後続で検討） |
| 対象 | **Phase 1: 珠洲 1/2 撮影（133枚, DMC）**。Phase 2 以降で他地区 | 4月撮影分（正射画像のみ公開、単写真なし） |

### パイロットを珠洲 1/2 にする理由

- 単一日・単一カメラ（DMC）で構成が均質（Qiita 記事の「年度を混ぜない」教訓）
- 133枚・約230MB とサイズが手頃で、GPU 1枚で数十分〜1時間台の見込み
- 珠洲は隆起・津波・家屋倒壊が混在し、地理院 1mDSM との比較で違いが出やすい
- 主点間隔約1050m・7コースで、SfM に必要なオーバーラップが確認済み（notes.md §7）

## 3. 入力データ

### 3.1 垂直写真メタデータ（地理院地図 GeoJSON）

```
https://maps.gsi.go.jp/xyz/20240102noto_<district>_<MMDD>suichoku/2/3/1.geojson
```

- 1フィーチャ = 1枚。Point（主点の経緯度, WGS84）
- プロパティ: `name`(地区), `コース番号`, `写真番号`, `画像`(HTML; 中に JPEG 直リンク), `撮影日`
- 地区名の綴り: レイヤ id は `wazima*`、タイル URL は `wajima*`（`wazimanishii`→`wajimanishi`）
- ここから取り出すもの: **写真URL, 主点 lon/lat, コース, 写真番号, 撮影時刻**

### 3.2 写真本体

```
https://saigai.gsi.go.jp/1/R6_0101notohanto/<MMDD><district>_<camera>/photo/qv/<NNNN>.jpg
```

| 項目 | 値（珠洲 1/2 実測） |
|---|---|
| 画素数 | 3648 × 6432 px（長辺 = 進行方向） |
| ファイル | JPEG RGB, 約1.7MB, **EXIF なし** |
| 元カメラ | Leica DMC III（原寸 14592×25728, 画素 3.9µm, 焦点距離 92mm）の 1/4 縮小 |
| 実効 GSD | ≈ 0.8 m/px（原寸 GSD 0.2m 想定） |
| 主点間隔 | 約1050 m（同一コース） → 進行方向オーバーラップ約80% |
| 撮影範囲 | lon 137.164〜137.378, lat 37.363〜37.558 |

未確認: 実際の対地高度・コース間隔（サイドラップ）。GeoJSON の隣接コース主点間距離から推定する（§5.2）。

### 3.3 比較・検証用（正解側）

| データ | URL | 用途 |
|---|---|---|
| 地理院 SfM DSM 1m | `https://maps.gsi.go.jp/xyz/20240102noto_1mDSM/{z}/{x}/{y}.png` | DSM の直接比較 |
| 地理院 正射画像 1/2 珠洲 | `https://maps.gsi.go.jp/xyz/20240102noto_suzu_0102do/{z}/{x}/{y}.png` (z10–18) | 位置ずれ・オルソ品質の比較 |
| 基盤地図情報 DEM5A/B | 地理院標高タイル `dem5a_png` 等 | 地震前の地盤高（変化のない場所での鉛直精度確認） |

## 4. 処理環境

- Windows 11 / Ryzen 7 5700X (16T) / RAM 64GB / RTX 4060 8GB / Docker Desktop (WSL2)
- ODM: `opendronemap/odm:gpu`（バージョンは初回 pull 時に `docker image inspect` で記録し、README に固定値を書く）
- `.wslconfig` に `memory=48GB`, `processors=14`, `swap=16GB` を設定してから実行
- Python 3.12（ダウンローダ・タイル変換）: requests, Pillow, piexif, numpy, GDAL（OSGeo4W or conda）

## 5. 処理フロー

```
[A] メタデータ取得   GeoJSON → photos.csv（url, lon, lat, course, no, time）
        │
[B] 写真取得         qv JPEG を datasets/<proj>/images/ へ（1秒間隔, リトライ, 再開可）
        │
[C] 前処理           EXIF 注入（GPS, FocalLength, Make/Model）+ geo.txt + cameras.json
        │
[D] ODM 実行         docker run ... opendronemap/odm:gpu --dsm --orthophoto ...
        │
[E] 後処理           dsm.tif → EPSG:3857 → 地理院標高タイル PNG（z10–17）
        │
[F] 検証・可視化     MapLibre で 1mDSM と並置、サンプル点で差分統計
```

### 5.1 [A] メタデータ取得 `scripts/01_fetch_metadata.py`

- 引数: `--layer 20240102noto_suzu_0102suichoku`（複数可）
- `/2/3/1.geojson` を取得し、`画像` プロパティから `index_dmc.html?<path>&<deg>` の `<path>` を正規表現で抜く
  → `https://saigai.gsi.go.jp/1/<path>`
- 出力 `datasets/<proj>/photos.csv`: `file,url,lon,lat,course,photo_no,shot_time,rotation_deg`
- `rotation_deg` は地理院ビューアの回転角（≒ 機首方位の補正値）。yaw の初期値に使える可能性があるので保持

### 5.2 [B] 写真取得 `scripts/02_fetch_photos.py`

- photos.csv を読み、`images/<course>_<photo_no>.jpg` として保存（例 `C01_0001.jpg`）
- 1リクエスト/秒、サイズ一致でスキップ、失敗は3回リトライ（再開可能）
- 取得後に Pillow でサイズ検査（3648×6432 以外を警告）
- 同時に**コース間隔**を算出してログに出す（隣接コースの最近傍主点距離の中央値）
  → 対地高度 H と GSD の推定に使う

### 5.3 [C] 前処理 `scripts/03_prepare_odm_inputs.py`

ODM/OpenSfM は EXIF に GPS と焦点距離が無いと位置は無視・焦点距離はデフォルト比で始める。
OpenSfM の再構成を安定させるため両方与える。

**EXIF 注入（piexif）**

| タグ | 値 | 根拠 |
|---|---|---|
| GPSLatitude/Longitude | GeoJSON の主点 | 概略位置（数十m精度想定） |
| GPSAltitude | 推定対地高度 + 地盤高 | H ≈ GSD × f / pixel = 0.2 × 0.092 / 3.9e-6 ≈ **4,700 m**（要検証） |
| FocalLength | 92 mm | DMC III 公称 |
| FocalLengthIn35mmFilm | 33 mm | 焦点比 92 / 100.3(長辺センサ幅) = 0.917 → ×36 |
| Make / Model | `Leica` / `DMC III qv` | OpenSfM のカメラ ID をそろえる |
| DateTimeOriginal | 撮影時刻 | – |

**geo.txt（`--geo` で渡す）**

```
EPSG:4326
C01_0001.jpg 137.377993 37.543885 4750 0 0 0 30 50
...
```
列: `image lon lat alt yaw pitch roll horiz_acc vert_acc`。yaw は `rotation_deg` から試算（効果を見て採否）。
EXIF GPS と重複するが、`--geo` の方が精度値を明示できるので両方用意し、実行時は `--geo` を正とする。

**cameras.json（任意）**: 1回目の実行で ODM が出力する `cameras.json` を保存し、2回目以降 `--cameras` で渡して
焦点距離・歪みを固定。Phase 2 で複数地区を処理するときにカメラ別（DMC / UCE / UCO）に持つ。

### 5.4 [D] ODM 実行 `scripts/04_run_odm.ps1`

```powershell
docker run -ti --rm --gpus all `
  -v C:\Users\yshiw\Documents\GIS\odm-aerial-photo-sfm\datasets:/datasets `
  opendronemap/odm:gpu --project-path /datasets suzu_0102 `
  --geo /datasets/suzu_0102/geo.txt `
  --feature-type sift --feature-quality high --min-num-features 12000 `
  --matcher-type flann --matcher-neighbors 12 `
  --camera-lens brown `
  --gps-accuracy 30 `
  --pc-quality high --pc-classify `
  --dsm --dtm --dem-resolution 100 `
  --orthophoto-resolution 100 `
  --cog --auto-boundary `
  --max-concurrency 14
```

| パラメータ | 値 | 理由 |
|---|---|---|
| `--feature-type sift` | GPU 版で高速化される特徴量 | README 記載 |
| `--min-num-features 12000` | 既定 10000 より増 | 雪・海・畑でテクスチャが乏しい |
| `--matcher-neighbors 12` | 位置情報ベースの近傍マッチ | 7コース格子飛行。全対全は不要 |
| `--gps-accuracy 30` | 30 m | 主点座標は概略、高度は推定値 |
| `--dem-resolution 100` | **cm 単位** = 1 m | 実効 GSD 0.8m から妥当。地理院 1mDSM と合わせる |
| `--orthophoto-resolution 100` | 1 m | 同上 |
| `--pc-classify --dtm` | 地盤分類 | 副産物として DTM も見る |
| `--cog` | COG 出力 | QGIS / 後処理で扱いやすい |
| `--3d-tiles` | 初回は付けない | 処理時間短縮。DSM が出てから追加実行 |

ログは `datasets/suzu_0102/odm_log.txt` へ tee し、`--time` で段階ごとの所要時間を記録する。

### 5.5 [E] 後処理 `scripts/05_dsm_to_gsi_tiles.py`

- 入力: `datasets/suzu_0102/odm_dem/dsm.tif`（ODM 出力の UTM 53N）
- `gdalwarp -t_srs EPSG:3857 -r bilinear` → 一時 GeoTIFF
- 地理院標高タイル PNG エンコード（数値標高 h → RGB）:
  - `x = round(h / 0.01)`; `x < 0` なら `x += 2^24`; `R = x>>16, G = (x>>8)&255, B = x&255`
  - 無効値は `(128, 0, 0)`
- 256px タイル、z10〜17（z17 で約1.19 m/px@lat37 なので 1m DSM の上限）。z16 以下は平均で縮小
- 出力: `output/suzu_0102/dsm_tiles/{z}/{x}/{y}.png` + `metadata.json`（範囲・ズーム・出典）
- 参考: ODM の正射画像も既存の `aerial-photo-tile-pipeline` で XYZ タイル化して重ねる

### 5.6 [F] 検証・可視化

**ビューア** `viewer/`（MapLibre GL JS、既存の noto DSM ビューアをベースに）
- terrain ソースを「自作 DSM」「地理院 1mDSM」で切替、hillshade で見比べ
- 正射画像（自作 / 地理院 `suzu_0102do`）のスワイプ

**定量比較** `scripts/06_compare_dsm.py`
- 地理院 1mDSM PNG を同ズームでデコードし、自作 DSM と画素単位で差分 → 平均・RMSE・ヒストグラム
- 地震で変化していない場所（道路・空き地）を数十点選び、DEM5A とも比較して絶対精度の目安を出す
- 結果は `docs/results-suzu_0102.md` に表と図で残す

## 6. ディレクトリ構成

```
odm-aerial-photo-sfm/
├── README.md
├── docs/
│   ├── notes.md            # 調査メモ
│   ├── design.md           # 本書
│   └── results-<proj>.md   # 実行結果・比較
├── scripts/
│   ├── 01_fetch_metadata.py
│   ├── 02_fetch_photos.py
│   ├── 03_prepare_odm_inputs.py
│   ├── 04_run_odm.ps1
│   ├── 05_dsm_to_gsi_tiles.py
│   └── 06_compare_dsm.py
├── config/
│   └── cameras/            # dmc3_qv.json, uce_qv.json ...
├── datasets/               # git 管理外
│   └── suzu_0102/
│       ├── photos.csv
│       ├── geo.txt
│       ├── images/
│       └── (ODM 出力: odm_dem/, odm_orthophoto/, odm_georeferencing/ ...)
├── output/                 # git 管理外（タイル）
└── viewer/
```

## 7. リスク・未確定事項

| 項目 | 影響 | 対応 |
|---|---|---|
| 対地高度・焦点比の推定が外れる | 初期再構成が歪む／スケールが狂う | コース間隔から逆算して検証。`--gps-accuracy` を緩めて OpenSfM に補正させる。必要なら GCP 数点 |
| qv 縮小で建物側面・細部が出ない | DSM がなだらかになる | 前提として受容。地理院 1mDSM も同系統の限界がある |
| 雪・海面・雲でマッチ失敗 | コース端や海側で穴 | `--min-num-features` 増、`--auto-boundary`。穴は無効値のまま出す |
| 8GB VRAM で SIFT がメモリ不足 | GPU 段で落ちる | `--feature-quality medium` にフォールバック（qv 解像度なら影響小） |
| saigai.gsi.go.jp への負荷 | 遮断リスク | 1req/s、再開可能にして一気に取り直さない |
| 4月撮影分は単写真非公開 | 地震後数ヶ月の比較不可 | スコープ外と明記 |

## 8. 完了条件（Phase 1）

- [ ] 珠洲 1/2 の 133 枚が取得され、photos.csv / geo.txt が生成されている
- [ ] ODM が最後まで走り、`dsm.tif` / `odm_orthophoto.tif` / `.laz` が出ている（所要時間を記録）
- [ ] 地理院標高タイル PNG（z10–17）が出力され、MapLibre ビューアで 1mDSM と切替表示できる
- [ ] 1mDSM との差分統計（平均・RMSE）と、代表箇所のスクリーンショットが `docs/results-suzu_0102.md` にある
- [ ] README に再現手順（環境構築 → 6スクリプト）が書かれている

## 9. Phase 2 以降（メモ）

- 他地区（輪島東 1/2, 輪島西, 穴水 1/17, 七尾 1/5）を同手順で。UCE/UCO 用のカメラ定義を追加
- 同一地区の別日（珠洲 1/2 vs 1/14）で DSM 差分 → 応急復旧や余震による変化の検出を試す
- 地理院地図から GCP を数点拾って精度改善（Qiita 記事の手順）
- 3D Tiles 出力と点群配信
