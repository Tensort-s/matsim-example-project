# 基于 WEDAN OD 生成 MATSim Agents

本文档记录当前 v1 的福州 Greenspace 新格网 OD → MATSim population 生成流程。

## 输入数据

默认脚本使用以下输入：

- OD 矩阵：`data/worldcommuting_od/custom_features/fuzhou_city_23_greenspace_grid/CommutingODFlows/fuzhou_city_23_greenspace_grid/generation.npy`
- 新格网：`data/worldcommuting_od/custom_features/fuzhou_city_23_greenspace_grid/CityAndRegionSplit/fuzhou_city_23_greenspace_grid/regions.shp`
- 居住人口权重：`data/gee/fuzhou_city_23/worldpop_age_sex/worldpop_CHN_2020_pop_age_sex_fuzhou_city_23_greenspace_boundary.tif`
- 工作吸引点：`data/osm/fuzhou_city_23/fuzhou_city_23_osm_work_pois.geojson`

坐标约定：

- MATSim `x/y`：`EPSG:32650`
- debug 经纬度：`EPSG:4326`

## 运行命令

在项目根目录运行：

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\generate_matsim_agents_from_wedan_od.py
```

默认生成 30,000 个 car-only 通勤 agents。可通过参数调整：

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\generate_matsim_agents_from_wedan_od.py `
  --target-agents 30000 `
  --seed 20260703 `
  --mode car
```

## 输出文件

默认输出目录：

`data/matsim_agents/fuzhou_city_23_greenspace_grid/`

包含：

- `plans.xml.gz`：MATSim `population_v6` 格式 population/plans。
- `agent_od_debug.csv`：每个 agent 的 OD、坐标、经纬度、时间、抽样方法。
- `od_sampled_matrix.npy`：整数化后的 438×438 agent OD 矩阵。
- `od_sampled_edges.csv`：被抽中的 OD pair 及其原始 flow、缩放期望值、抽样误差。
- `agents_home_work_points.geojson`：home/work 点，可在 QGIS 中叠加 `regions.shp` 检查。
- `generation_to_agents_summary.json`：输入、输出、抽样、空间校验和 OD 相关性摘要。

## 当前 v1 生成逻辑

1. 读取 `generation.npy`，将对角线 OD 置 0。
2. 按目标 agent 数缩放原始 OD 总量。
3. 使用保总量随机舍入把连续 flow 转为整数 agent 数。
4. 对每个被抽中的 OD pair 生成一个或多个 agents。
5. home 点优先按 WorldPop 像元人口权重采样；无有效人口像元时在 origin polygon 内均匀采样。
6. work 点优先从 office / education / health / commercial / industrial 等 OSM 工作 POI 中采样；无 POI 时在 destination polygon 内均匀采样。
7. 每个 agent 写入 `h → car → w → car → h` selected plan。
8. 上班出发时间服从 `07:00–09:30` 三角分布，峰值约 `08:00`。
9. 下班时间为上班出发后约 `8–9` 小时。

注意：当前 OD 原始总量约 2791 万，默认只抽样 3 万 agents。因此每个 OD pair 缩放后的期望值均小于 1；严格随机舍入下，被抽中的 OD pair 当前最多对应 1 个 agent。这适合做轻量仿真样本。如果希望高流量 OD 在样本中更频繁重复，可在后续版本增加 multinomial 抽样模式。

## MATSim 接入方式

当前 `plans.xml.gz` 是坐标型 plans，不写 `link id`。在福州 MATSim network 建好后，可以：

1. 直接在 config 中将 population input 指向该文件；
2. 或先做 home/work 点到 network link 的 snapping；
3. 再由 MATSim routing 在仿真初始化或 replanning 中生成 route。

## v2 Valhalla 预留

下一阶段可加入 Valhalla：

- 使用 `fujian-latest.osm.pbf` 裁剪出的福州 OSM 建立 Valhalla tiles；
- 对 home/work 点做 nearest-road snapping；
- 批量计算 OD travel time / distance；
- 剔除不可达 OD 或重采样不可达点；
- 用 Valhalla 成本修正 OD 权重或为 MATSim 初始路径提供参考。

