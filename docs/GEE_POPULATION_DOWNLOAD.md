# GEE 下载福州人口数据并生成 WEDAN 人口特征

本项目可以直接用 Google Earth Engine 下载福州人口栅格，然后转成 WorldCommuting-OD/WEDAN 推理需要的节点人口特征。

## 1. 首次登录 Earth Engine

项目本地 Python 环境已经安装 `earthengine-api`。第一次运行需要浏览器授权：

```powershell
cd F:\Matsim\matsim-example-project
.\.venv_geo311\Scripts\python.exe scripts\download_fuzhou_population_from_gee.py --authenticate --project YOUR_GEE_PROJECT
```

把 `YOUR_GEE_PROJECT` 换成你已经启用 Earth Engine 的 Google Cloud project。授权成功后，后续可以省略 `--authenticate`：

```powershell
.\.venv_geo311\Scripts\python.exe scripts\download_fuzhou_population_from_gee.py --project YOUR_GEE_PROJECT
```

默认下载：

- 数据集：`WorldPop/GP/100m/pop`
- 国家：`CHN`
- 年份：`2020`
- 波段：`population`
- 边界：`data/osm/fuzhou/city_23/fuzhou_city_23_boundary.geojson`
- 输出：`data/gee/fuzhou/city_23/worldpop_CHN_2020_population_fuzhou_city_23.tif`

## 2. 转成 WEDAN 的 `worldpop.npy`

下载完成后运行：

```powershell
.\.venv_geo311\Scripts\python.exe scripts\build_fuzhou_population_features.py --copy-demos
```

输出目录：

```text
data/worldcommuting_od/fuzhou/custom_features/fuzhou_city_23_population/nfeat/
```

主要文件：

- `worldpop.npy`：形状为 `(225, 2)`，对应 WorldOD 福州 225 个分区；
- `worldpop_region_features.csv`：便于检查的表格；
- `feature_generation_summary.json`：记录输入、输出、总人口、特征定义；
- `demos.npy`：如果使用 `--copy-demos`，会复制 WorldCommuting-OD 自带的 36 维人口结构参考文件。

## 3. 关于 36 维人口结构 `demos.npy`

Greenspace 当前福州数据主要是总人口/人口密度栅格，不能直接推导真实的年龄-性别 36 维结构。因此脚本只把总人口栅格转换成 `worldpop.npy`。

如果需要完整、真实的 `demos.npy`，应另外下载年龄-性别分组人口数据；在此之前，`--copy-demos` 只是为了让 WEDAN 推理输入形状完整，来源是 WorldCommuting-OD 的福州参考特征，不是从 Greenspace 或 GEE 总人口栅格反演得到的。

## 4. 下载年龄-性别分组人口栅格

如果需要真实的年龄-性别分组人口，可以下载 Earth Engine 数据集 `WorldPop/GP/100m/pop_age_sex`：

```powershell
.\.venv_geo311\Scripts\python.exe scripts\download_fuzhou_age_sex_population_from_gee.py --project YOUR_GEE_PROJECT
```

首次授权时：

```powershell
.\.venv_geo311\Scripts\python.exe scripts\download_fuzhou_age_sex_population_from_gee.py --authenticate --project YOUR_GEE_PROJECT
```

默认使用 Greenspace 的福州 `city_id=23` 城市边界：

```text
data/osm/fuzhou/city_23/fuzhou_city_23_boundary.geojson
```

输出目录：

```text
data/gee/fuzhou/city_23/worldpop_age_sex/
```

输出 GeoTIFF 是多波段文件，包含 `population`、`M_0` 到 `M_80`、`F_0` 到 `F_80`。这些 band 是每个网格内对应年龄/性别组的估计人口数。

## 5. 基于 Greenspace 福州边界生成 WorldOD 风格网格与人口结构特征

下载年龄-性别栅格后，可以把 Greenspace 福州城市边界按 WorldOD 的方式网格化，并把人口、年龄、性别数据聚合到新网格：

```powershell
.\.venv_geo311\Scripts\python.exe scripts\build_fuzhou_greenspace_grid_population_features.py
```

默认设置：

- 目标边界：Greenspace 福州 `city_id=23`
- 目标坐标系：`EPSG:32650`
- 网格尺寸：从 WorldOD 福州完整网格推断，约 `920.659 m × 920.659 m`
- 网格原点：Greenspace 福州边界左下角
- 聚合方式：按像元中心分配到网格，避免相邻网格重复计数

输出目录：

```text
data/worldcommuting_od/fuzhou/custom_features/fuzhou_city_23_greenspace_grid/
```

关键输出：

- `CityAndRegionSplit/fuzhou_city_23_greenspace_grid/regions.shp`
- `CityAndRegionSplit/fuzhou_city_23_greenspace_grid/regions.geojson`
- `GeneratingCodeData/data/global_cities/fuzhou_city_23_greenspace_grid/nfeat/worldpop.npy`
- `GeneratingCodeData/data/global_cities/fuzhou_city_23_greenspace_grid/nfeat/demos.npy`
- `GeneratingCodeData/data/global_cities/fuzhou_city_23_greenspace_grid/nfeat/population_age_sex_grid_features.csv`

`worldpop.npy` 的形状为 `(N, 2)`：

1. `population_count`
2. `population_density_per_km2`

`demos.npy` 的形状为 `(N, 36)`：

```text
M_0, M_1, M_5, ..., M_80,
F_0, F_1, F_5, ..., F_80
```

## 6. 下载 Greenspace 福州边界内的 Esri World Imagery

WorldOD 的遥感影像特征来自 Esri World Imagery。可以用下面的脚本下载 Greenspace 福州 `city_id=23` 边界内的影像：

```powershell
.\.venv_geo311\Scripts\python.exe scripts\download_fuzhou_esri_world_imagery.py
```

默认设置：

- 数据源：Esri World Imagery XYZ tiles
- zoom：`14`，约接近 10 m 级别
- 边界：`data/osm/fuzhou/city_23/fuzhou_city_23_boundary.geojson`
- 输出目录：`data/imagery/fuzhou/esri_world_imagery/greenspace_boundary/`

主要输出：

- 原始瓦片：`tiles/`
- Web Mercator 拼接图：`*_mosaic_epsg3857.tif`
- Greenspace 边界裁剪图：`*_greenspace_clip_epsg3857.tif`
- UTM 50N 裁剪图：`*_greenspace_clip_epsg32650.tif`
- 瓦片清单：`tile_manifest_z14.json`
- 元数据：`*_metadata.json`

## 7. 从遥感影像生成 `imgfeat.npy`

下载并裁剪 Esri World Imagery 后，可以用 RemoteCLIP-RN50 为 Greenspace 福州新网格生成模型需要的 1,024 维遥感语义特征：

```powershell
.\.venv_wedan\Scripts\python.exe scripts\build_fuzhou_remoteclip_imgfeat.py --batch-size 16
```

输出：

```text
data/worldcommuting_od/fuzhou/custom_features/fuzhou_city_23_greenspace_grid/GeneratingCodeData/data/global_cities/fuzhou_city_23_greenspace_grid/nfeat/imgfeat.npy
```

当前形状：

```text
(438, 1024)
```

详细说明见：

```text
docs/REMOTECLIP_IMGFEAT_GENERATION.md
```
