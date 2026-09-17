# odm-aerial-photo-sfm

国土地理院の空中写真から OpenDroneMap（SfM）で点群・DSM・3D Tiles を作る検証リポジトリ。

- [docs/notes.md](docs/notes.md) — 参照記事・手順・2022→現在の差分・能登半島地震 SfM DSM の整理

## 想定ディレクトリ

```
datasets/<project>/images/   # 入力写真（git 管理外）
datasets/<project>/gcp_list.txt
```

## 実行例（Windows, NVIDIA GPU）

```sh
docker pull opendronemap/odm:gpu
docker run -ti --rm -v c:/Users/yshiw/Documents/GIS/odm-aerial-photo-sfm/datasets:/datasets --gpus all opendronemap/odm:gpu ^
  --project-path /datasets <project> --feature-type sift --dsm --3d-tiles --pc-quality high
```
