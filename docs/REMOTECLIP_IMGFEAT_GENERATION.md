# 生成 Greenspace 福州网格的 `imgfeat.npy`

WorldCommuting-OD 使用 Esri World Imagery，并通过 RemoteCLIP 的 image encoder 为每个区域提取 1,024 维遥感语义特征。本项目中，Greenspace 福州边界被重新网格化后，可以用以下脚本生成同格式的 `imgfeat.npy`。

## 输入

- 新网格：

```text
data/worldcommuting_od/custom_features/fuzhou_city_23_greenspace_grid/CityAndRegionSplit/fuzhou_city_23_greenspace_grid/regions.shp
```

- 福州 Esri World Imagery 裁剪影像：

```text
data/imagery/esri_world_imagery/fuzhou_city_23_greenspace_boundary/fuzhou_city_23_esri_world_imagery_z14_greenspace_clip_epsg32650.tif
```

## 运行

```powershell
cd F:\Matsim\matsim-example-project
.\.venv_wedan\Scripts\python.exe scripts\build_fuzhou_remoteclip_imgfeat.py --batch-size 16
```

首次运行会把 `RemoteCLIP-RN50.pt` 下载到：

```text
data/models/remoteclip/
```

## 输出

```text
data/worldcommuting_od/custom_features/fuzhou_city_23_greenspace_grid/GeneratingCodeData/data/global_cities/fuzhou_city_23_greenspace_grid/nfeat/imgfeat.npy
```

形状：

```text
(438, 1024)
```

含义：

- 行：Greenspace 福州新网格单元，顺序与 `regions.shp` 一致；
- 列：RemoteCLIP-RN50 输出的 1,024 维遥感影像语义特征；
- 特征没有做 L2 归一化，保持原始 image embedding。

## 当前生成结果

```text
worldpop.npy: (438, 2)
demos.npy:    (438, 36)
imgfeat.npy:  (438, 1024)
```

后续如果要完整运行 WEDAN，还需要为同一套 438 网格继续生成：

- `adj/dis.npy`

`pois.npy` 已可通过以下脚本生成：

```powershell
.\.venv_geo311\Scripts\python.exe scripts\build_fuzhou_osm_pois_features.py
```

详细说明见：

```text
docs/OSM_POIS_FEATURE_GENERATION.md
```
