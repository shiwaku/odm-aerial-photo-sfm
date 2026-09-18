# 結果: 珠洲 1/2 撮影 垂直写真 → ODM → DSM（Phase 1）

実行日: 2026-09-18 / ODM 3.6.2（`opendronemap/odm:gpu`, image id `c6ecdec77640`）/ RTX 4060 8GB, WSL2 メモリ 32GB

## 1. 入力

| 項目 | 値 |
|---|---|
| 写真 | 133 枚（7 コース, Leica DMC III, qv 版 3648×6432, 計 681 MB） |
| 主点間隔 / コース間隔 | 1008 m / 3148 m（中央値） |
| 与えた EXIF | GPS = 主点座標、GPSAltitude = 4223 m（地盤 100 + 推定 AGL 4123）、f = 92 mm、35mm換算 33 mm |
| geo.txt | 4 列（image lon lat alt）、`--gps-accuracy 30` |
| GCP | なし |

## 2. ODM 実行

`scripts/04_run_odm.ps1 -Project suzu_0102`（feature high / SIFT GPU / FLANN 12 近傍 / brown / pc-quality high / DSM 1 m / ortho 1 m / COG）

| 段階 | 所要 | メモ |
|---|---|---|
| opensfm | 9.6 分 | 特徴抽出 68 s、マッチング 54 s、再構成 209 s |
| openmvs | 5.9 分 | 密点群 25.9 M 点 |
| odm_filterpoints | 0.8 分 | |
| odm_meshing | 8.3 分 | |
| mvs_texturing | 13.0 分 | |
| odm_georeferencing | **90.4 分** | ほぼ全部が `--pc-classify`（SMRF）。次回は外す |
| odm_dem | 2.5 分 | DSM 13263×13816 px @1.23 m |
| odm_orthophoto | 1.6 分 | |
| odm_report | 0.5 分 | |

- 初回は DTM 生成で **exit 137**。SMRF が地盤点を返さず、renderdem が空点群の範囲から 2^31 px の DEM を割り当てて Killed。`--dtm --pc-classify` を外して `--rerun-from odm_dem` で完走
- 実行スクリプト側の事故: PowerShell 5.1 で `2>&1` + `ErrorActionPreference=Stop` のため最初の stderr 行で tee が落ちた（コンテナは継続）。04 で修正済み

### SfM 統計（`odm_report/stats.json`）

| 指標 | 値 |
|---|---|
| 再構成された写真 | **100 / 133** |
| 点数 / 観測数 | 280,685 / 735,219（平均トラック長 2.62） |
| 再投影誤差 | 0.54 px |
| GPS 残差（カメラ位置 − 与えた主点） | x 4.4 m, **y 25.1 m**, z 4.7 m（std）; 平均 6.8 m, CE90 5.8 m |
| 焦点比（最適化後） | 0.9106（事前値 0.9167） |
| 面積 | 381 km² |

- 外れた 33 枚は各コース両端の 2 枚と最東端コース C01 の 13 枚。海面が大半で特徴点が取れない写真で、オーバーラップ不足ではない
- GPS 残差が南北（コース方向）だけ大きい。主点座標の進行方向誤差（撮影時刻と位置の同期）が原因と考えられ、水平精度の目安は **数 m〜25 m**

## 3. DSM の高さ: 一定オフセット −463.7 m

補正前の DSM は地理院 1mDSM に対して **一律 −463.67 m**（中央値）低かった。

- 原因: 与えた GPS 高度（一定値 4223 m）が実際より低い。逆算すると実対地高度 ≈ 4587 m、原寸 GSD ≈ 0.194 m、側方オーバーラップ ≈ 37%（推定に使った 30% より広かった）
- 傾きは無視できる: タイル別中央値に平面を当てると dz/dx −0.01 m/km、dz/dy +0.33 m/km（21 km で 7 m 以下）
- 対処: `05_dsm_to_gsi_tiles.py --z-offset 463.67` で一律シフトしてタイル化。ODM の再実行は不要
- 次回同じデータを回すなら `03 --agl 4587` で最初から合わせる

## 4. 地理院 SfM 1mDSM との比較（z15 ≈ 4.8 m/px、有効画素 1,170 万）

`scripts/06_compare_dsm.py --project suzu_0102 --zoom 15` → [results-suzu_0102-vs-20240102noto_1mDSM-z15.md](results-suzu_0102-vs-20240102noto_1mDSM-z15.md)

| 指標 | 補正前 | オフセット補正後 |
|---|---|---|
| 平均 | −463.74 m | **−0.07 m** |
| 中央値 | −463.67 m | 0.00 m |
| 標準偏差 | 4.95 m | 4.95 m |
| RMSE | 463.77 m | **4.95 m** |
| MAD | 2.55 m | 2.55 m |
| 5% / 95% | −471.8 / −455.5 m | **−8.1 / +8.2 m** |

- 地理院 1mDSM も同じ写真群からの SfM 成果で「精度検証なし」の暫定値。両者の差 RMSE 4.95 m には双方の誤差が入る
- 差の分布は MAD 2.55 m に対して 5–95% が ±8 m と裾が広い。建物縁・樹冠・海岸線での DSM 表面の取り方の違いと、qv（0.7 m/px）由来のなだらかさが効いていると推定
- 絶対高の検証（DEM5A との比較）は未実施。地震前地盤との比較は隆起域を避ける必要がある

## 5. 成果物

| 種別 | パス | サイズ |
|---|---|---|
| DSM GeoTIFF（COG, UTM53N, 1.23 m） | `datasets/suzu_0102/odm_dem/dsm.tif` | 375 MB |
| 正射画像（COG） | `datasets/suzu_0102/odm_orthophoto/odm_orthophoto.tif` | 330 MB |
| 点群 LAZ | `datasets/suzu_0102/odm_georeferencing/odm_georeferenced_model.laz` | 167 MB |
| 地理院標高タイル PNG z10–17（+463.67 m 補正済） | `output/suzu_0102/dsm_tiles/` | 4,123 枚 / 293 MB |
| 正射画像 XYZ タイル z10–17 | `output/suzu_0102/ortho_tiles/` | 4,123 枚 / 432 MB |
| ODM レポート | `datasets/suzu_0102/odm_report/report.pdf` | |

ビューア: `python -m http.server 8000` → http://127.0.0.1:8000/viewer/ で自作 DSM / 地理院 1mDSM の terrain・陰影を切替、正射画像を重畳、クリックで両 DSM の値と差を表示。

## 6. 学んだこと・次にやること

- **GCP なしでも地理参照 DSM は成立する**。主点座標が水平位置とスケールを決め、相対形状は 1mDSM と RMSE 5 m 以内で一致した。絶対高だけは GPS 高度の仮定に依存する
- 高さの絶対値を出すなら (a) 1mDSM や DEM5A との中央値オフセット補正（今回）、(b) `--align` で参照 DEM に自動位置合わせ、(c) GCP 数点、の順に手間が増える
- `--pc-classify` は qv 解像度の航空写真 DSM では機能せず 90 分を浪費した。DTM が要る場合は別手段（DEM5A）を使う
- Phase 2 候補: 輪島東 1/2（UCE）でカメラ定義を追加して同手順、珠洲 1/14 との差分、`--3d-tiles` 出力
