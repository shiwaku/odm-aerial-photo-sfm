# 空中写真 × SfM（OpenDroneMap）メモ

作成: 2026-09-18

## 1. 参照した記事・ドキュメント

| 種別 | リンク | 要点 |
|---|---|---|
| Qiita | [無料で使える航空写真とOpenDroneMapを利用して、あなたの街の3Dデータ（点群）を作成する！](https://qiita.com/nokonoko_1203/items/97ee058dc6df4e399d02) | @nokonoko_1203（MIERUNE）、2022-07-08。地理院空中写真 + WebODM で札幌の点群を作る |
| 公式Docs | [ODM Installation](https://docs.opendronemap.org/installation/) | ほぼ「Desktop版を買うか GitHub 参照」しか書いていない。実質 README が正 |
| GitHub | [OpenDroneMap/ODM](https://github.com/OpenDroneMap/ODM) | Docker / GPU / Windowsネイティブ / Pixi ビルドの手順 |

## 2. Qiita記事（2022）の手順

1. **空中写真取得** — 地理院「地図・空中写真閲覧サービス」から DL。**単一年度で揃える**（複数年度混在は処理が破綻）
2. **WebODM構築** — Docker
   ```sh
   git clone https://github.com/OpenDroneMap/WebODM --config core.autocrlf=input --depth 1
   cd WebODM && ./webodm.sh start
   ```
3. **GCP設置** — 画像内で同定できる地点に、地理院地図から取った緯度経度・標高を割り当てテキスト化
4. **フォトグラメトリ実行** — 品質レベル・3D Tiles 出力を設定（記事では約16分）
5. **可視化** — 出力 3D Tiles の tileset.json を Cesium.js から参照

- 環境要件: 新しめCPU / ディスク100GB / RAM 16GB（Dockerに3/4割当）
- 精度: 元画像の解像度・枚数不足で **水平誤差60cm以上、垂直誤差数m**。建物側面のディテールはほぼ出ない

## 3. 2022年 → 現在（2026-09）の差分

| | 記事（2022） | 現在 |
|---|---|---|
| 入口 | WebODM を clone → `./webodm.sh start` | **ODM 単体 Docker イメージ**で CLI 実行が最短。GUI は WebODM（OSS）or 有償 OpenDroneMap Desktop |
| GPU | 言及なし | `opendronemap/odm:gpu` + `--gpus all` で SIFT 特徴抽出 約2倍速。バージョン固定は `opendronemap/odm:<version>-gpu` |
| ソースビルド | – | **Pixi** ベース（`pixi install --locked` / `pixi run build` / `pixi run odm -- --project-path ~/datasets mydataset`） |
| 動画入力 | – | 3.0.4 以降 MP4/MOV/LRV/TS から自動フレーム抽出、SRT の GPS 対応 |
| Windows | Docker のみ | ネイティブインストーラーあり（ODM コンソールで `run C:\...\project`） |
| 推奨スペック | 新しめCPU / 100GB / 16GB | 変更なし（最小: 64bit CPU / 20GB / 4GB） |

### 最小実行例（Windows, NVIDIA GPU あり）

```sh
docker pull opendronemap/odm:gpu
docker run -ti --rm -v c:/Users/yshiw/datasets:/datasets --gpus all opendronemap/odm:gpu ^
  --project-path /datasets project --feature-type sift --dsm --3d-tiles --pc-quality high
```

- 入力: `datasets/project/images/` に写真を置く
- 主要出力: `odm_orthophoto/odm_orthophoto.tif` / `odm_georeferencing/odm_georeferenced_model.laz` / `odm_texturing/odm_textured_model_geo.obj` / `odm_dem/dsm.tif` / `3d_tiles/`
- 関連: NodeODM（ネットワーク経由 API）、WebODM（GUI）

## 4. このマシンの状態（2026-09-18 時点）

- CPU: AMD Ryzen 7 5700X（16 thread） / RAM: 64GB / GPU: RTX 4060 8GB（driver 591.86）→ `odm:gpu` 利用可
- ディスク: C: 1.2TB 空き、D: 3.9TB 空き
- Docker 27.5.1 導入済みだが **Docker Desktop 停止中**（`docker-desktop` WSL ディストリも Stopped）
- `.wslconfig` なし → WSL2 メモリ上限デフォルト（物理の50% = 32GB）。大きめタスクなら `memory=48GB` 程度を明示
- pixi 未導入（ソースビルドしないなら不要）

### 次にやるなら
1. Docker Desktop 起動 → `docker pull opendronemap/odm:gpu`
2. 地理院空中写真を1年度分揃えて `datasets/<project>/images/` へ
3. GCP ファイル作成（記事の手動方式より楽な手を検討）
4. 上記コマンドで実行

## 5. 地理院の同種事例: 令和6年能登半島地震 SfM DSM

**「令和６年能登半島地震後の地形の状況が３Ｄで確認できるようになりました」**
https://www.gsi.go.jp/johofukyu/johofukyu240122_00001.html

- データ名: 数値表層モデル（DSM）
- 手法: 地震後に撮影した空中写真から **SfM で生成**（ODM と同じ原理）
- 元写真: 珠洲（1/2, 1/14）、輪島東（1/2, 1/14）、輪島中（1/11）、輪島西（1/11, 1/17）、穴水（1/17）、七尾（1/5, 1/17）
- 格子間隔: 初版 2m（2024-01-22 公開）→ **2024-02-16 更新で 1m** に高密度化・範囲拡大
- 地理院地図: レイヤ表示 → ツール → 3D
- 断り書き: 「測量成果ではなく、精度検証は実施していない」

### タイルURL（地理院標高タイル PNG 形式）

```
https://maps.gsi.go.jp/xyz/20240102noto_1mDSM/{z}/{x}/{y}.png
```

同期間の正射画像タイルもセットで公開。

### 関連

- 自作ビューア: [令和6年能登半島地震 被災状況3Dマップ](https://shiwaku.github.io/noto-peninsula-earthquake-2024-gsi-dsm-on-maplibre/)（[repo](https://github.com/shiwaku/noto-peninsula-earthquake-2024-gsi-dsm-on-maplibre)）— 上記 DSM を MapLibre terrain に使用。斜面崩壊分布・津波浸水域・焼失範囲・亀裂分布を重畳
- [3Dモデル閲覧サイト](https://maps.gsi.go.jp/noto/) — 地理院の Cesium ベース閲覧ページ
- [能登半島地震に関する情報（地理院）](https://www.gsi.go.jp/BOUSAI/20240101_noto_earthquake.html)
- **2025年の航空レーザー測量 DSM は別物**（[QGIS LAB by MIERUNE の記事](https://qgis.mierune.co.jp/posts/usecase_g-data_fa_2025_noto)が扱っているのはこちら）。SfM 版 = 速報性優先の暫定 DSM、LiDAR 版 = 後から入った測量成果

## 6. ODM の入力は「垂直写真」であって「正射画像」ではない

**結論: ODM に入れるのは垂直写真（単写真）。正射画像は入力にできない。**

- SfM/MVS は「同じ地物を別の位置から撮った複数枚の見え方のズレ（視差）」から三次元を復元する。
  垂直写真は隣と 60〜80% 重なり、建物や斜面の倒れ込みが写真ごとに違う → このズレが高さの源
- 正射画像はその倒れ込みを DSM で補正して真上視に引き延ばした**加工済み成果物**。視差が消えているので
  ODM に入れても特徴点マッチングが成立せず高さは出ない
- 地理院の能登 DSM も「空中写真を SfM で処理」したもので、正射画像は DSM と一緒に出てくる**出力側**

```
垂直写真（単写真・重複あり）
   └─ SfM/MVS（ODM / 地理院の処理）
        ├─ 点群
        ├─ DSM        ← 作りたいもの
        └─ 正射画像    ← 副産物（DSM で歪みを補正した結果）
```

→ 地理院の正射画像タイル（`*_do`）と 1mDSM タイルは、自分の ODM 出力と**比較する正解側**として使う。

## 7. 能登の垂直写真（単写真）の所在と諸元（2026-09-18 調査）

### 地理院地図のレイヤ定義

- 災害レイヤの索引: `https://maps.gsi.go.jp/layers_txt/layers6.txt`（「近年の災害」）
- 能登の定義本体: `https://maps.gsi.go.jp/layers_txt/layers_20240102noto.txt`
- 正射画像: `https://maps.gsi.go.jp/xyz/20240102noto_<地区>_<MMDD>do/{z}/{x}/{y}.png`（z10〜18）
  - 例: `20240102noto_suzu_0102do`, `20240102_noto_suzu_0105do`（1/5 撮影分だけ `20240102_noto_` と `_` 入り）, `20240102noto_0405_0426do`（4月撮影・全域）
- 垂直写真: `https://maps.gsi.go.jp/xyz/20240102noto_<地区>_<MMDD>suichoku/{z}/{x}/{y}.geojson`
  - **`/2/3/1.geojson` で全件取れる**（例: 珠洲 1/2 = 133 フィーチャ, 177KB）
  - 地区名の綴りに注意: レイヤ id は `wazima`、タイル URL は `wajima`（`wazimanishii` → `wajimanishi` など）
  - 1フィーチャ = 1枚。Point（主点の経緯度）。プロパティ: `name`(地区), `コース番号`, `写真番号`, `画像`(HTML, 直リンク入り), `撮影日`(例 `2024年1月2日 11時22分51秒`), `備考`
  - プロパティ名は日本語。ファイルは UTF-8（Git Bash 上で cp932 に化けて見えるだけ）

### 写真本体

```
https://saigai.gsi.go.jp/1/R6_0101notohanto/<MMDD><地区>_<カメラ>/photo/qv/<NNNN>.jpg
```

| 地区・日付 | 枚数 | ディレクトリ | カメラ |
|---|---|---|---|
| 珠洲 1/2 | 133（7コース C01〜C07） | `0102suzu_DMC` | DMC |
| 珠洲 1/14 | 33 | – | – |
| 輪島東 1/2 | 129 | `0102wajima_east_UCE` | UltraCam Eagle |
| 輪島中 1/11 | 56 | – | – |
| 輪島西 1/11 | 168 | – | – |
| 輪島西 1/17 | 54 | `0117wajima_west_UCE` | UltraCam Eagle |
| 穴水 1/17 | 219 | `0117anamizu_UCE` | UltraCam Eagle |
| 七尾 1/5 | 218 | `0105nanao_UCO` | UltraCam Osprey |

- 珠洲 1/2 の 0001.jpg を実測: **3648 × 6432 px, 約 1.7MB, EXIF なし**（GPS・焦点距離とも空）
- DMC III 原寸 14592×25728 のちょうど **1/4 縮小**（"qv" = クイックビュー）。実効 GSD は 80cm/px 前後
- 同一コース内の主点間隔 **約 1050 m** → 原寸 GSD 20cm 想定で進行方向オーバーラップ約 80%。SfM には十分
- 原寸版はサーバー上に見当たらず（`photo/`直下, `full/`, `org/`, `hr/`, `.tif` すべて 404）。ディレクトリ一覧は 403
- 閲覧サービス（service.gsi.go.jp/map-photos）側の無料DLも 400dpi 縮小（1200dpi の 1/3）・一括DL不可。災害撮影分は閲覧サービスではなく防災ページ側での公開
- 閲覧ページ `https://saigai.gsi.go.jp/1/index_dmc.html?<path>&<回転角>deg` は Leaflet で1枚表示するだけ
- 珠洲 1/2 の範囲: lon 137.164〜137.378, lat 37.363〜37.558
- 利用: 国土地理院コンテンツ利用規約（出典明示）。一括DLは間隔を空ける

### 出来上がる DSM の見込み

- qv 解像度（≈80cm/px）からなので、DSM は 1〜2m 格子が現実的 → 地理院の 1mDSM と同レベル
- 期待精度は Qiita 記事と同程度（水平数十cm〜m、鉛直数m）。GCP を入れれば改善余地あり

### 計画（珠洲 1/2 をパイロットに）

1. ダウンローダ（Python）: GeoJSON → JPEG 一括取得 → ODM 用 `geo.txt`（画像名, 経度, 緯度, 推定高度）生成。
   EXIF に GPS と焦点距離を注入して ODM のカメラ推定を助ける（DMC III: 焦点距離 92mm, 画素 3.9µm; qv は 1/4 なので 15.6µm 相当）
2. 珠洲 1/2（133枚, 約230MB）: 単一日・単一カメラで「年度を混ぜない」教訓に合う
3. ODM GPU: `--dsm --dem-resolution 1 --pc-quality high --geo geo.txt`。主点座標は概略なので `--gps-accuracy` は緩めに
4. `odm_dem/dsm.tif` → 地理院標高タイル PNG に変換し、`20240102noto_1mDSM` と MapLibre 上で並べて比較（既存ビューア流用）
