# 生成 Greenspace 福州新网格的 `adj/dis.npy`

`dis.npy` 是 WEDAN/WorldOD 风格的区域间距离矩阵。本项目当前版本使用新福州 438 个网格 polygon 的 centroid 计算两两直线距离。

## 输入

```text
data/worldcommuting_od/fuzhou/custom_features/fuzhou_city_23_greenspace_grid/CityAndRegionSplit/fuzhou_city_23_greenspace_grid/regions.shp
```

## 运行

```powershell
cd F:\Matsim\matsim-example-project
.\.venv_geo311\Scripts\python.exe scripts\build_fuzhou_grid_dis_matrix.py
```

## 输出

```text
data/worldcommuting_od/fuzhou/custom_features/fuzhou_city_23_greenspace_grid/GeneratingCodeData/data/global_cities/fuzhou_city_23_greenspace_grid/adj/dis.npy
```

形状：

```text
(438, 438)
```

## 口径

- 距离类型：网格 centroid 到 centroid 的欧氏直线距离；
- 计算坐标系：`EPSG:32650`；
- 默认单位：米；
- 对角线：`0`；
- 矩阵：对称矩阵。

当前统计：

```text
min_nonzero_distance: 155.005 m
max_distance:         40870.262 m
mean_non_diag:        12218.613 m
```

辅助输出：

```text
grid_centroids.csv
dis_matrix_sample_20x20.csv
dis_generation_summary.json
```
