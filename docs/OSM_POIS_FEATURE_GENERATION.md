# 生成 Greenspace 福州网格的 `pois.npy`

WorldCommuting-OD 使用 34 类 POI 计数作为区域节点特征。本项目基于已下载的福州 OSM POI 点数据，将 POI 聚合到 Greenspace 福州新网格，生成同格式的 `pois.npy`。

## 输入

- 新网格：

```text
data/worldcommuting_od/fuzhou/custom_features/fuzhou_city_23_greenspace_grid/CityAndRegionSplit/fuzhou_city_23_greenspace_grid/regions.shp
```

- OSM POI：

```text
data/osm/fuzhou/city_23/fuzhou_city_23_osm_pois.geojson
```

## 运行

```powershell
cd F:\Matsim\matsim-example-project
.\.venv_geo311\Scripts\python.exe scripts\build_fuzhou_osm_pois_features.py
```

## 输出

```text
data/worldcommuting_od/fuzhou/custom_features/fuzhou_city_23_greenspace_grid/GeneratingCodeData/data/global_cities/fuzhou_city_23_greenspace_grid/nfeat/pois.npy
```

形状：

```text
(438, 34)
```

行顺序与 `regions.shp` 一致，列顺序记录在：

```text
poi_categories.json
```

34 类 POI 顺序为：

```text
finance, toilets, transport, cinema and theatre, health, service,
education, government, religion, accommodation, bar, cafe, fast food,
ice cream, food court, restaurant, beauty shop, clothes shop, boutique,
bicycle shop, retail, supermarket, houseware shop, sport, transit station,
kindergarten, office, recycling, travel agency, tourism, livelihood shop,
residential, dormitory, garden
```

## 当前结果

```text
input_pois:       6714
categorized_pois: 6162
unmatched_pois:    552
pois.npy sum:     6139
nonzero grids:     374 / 438
```

没有匹配到 34 类的 OSM 点不会进入 `pois.npy`。这些点的常见 tag 组合记录在：

```text
pois_generation_summary.json
```

POI 映射规则记录在：

```text
poi_mapping_policy.json
```

默认采用单标签优先级分配：每个 POI 只计入最具体的一个类别，避免同一 POI 被重复计数。如果需要多标签计数，可运行：

```powershell
.\.venv_geo311\Scripts\python.exe scripts\build_fuzhou_osm_pois_features.py --multi-label
```
