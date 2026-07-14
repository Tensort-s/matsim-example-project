# 基于年龄-性别人口结构的多活动 MATSim Agents

本文档记录当前 v2 的福州 Greenspace 新格网 multi-activity population 生成流程。

## 运行方式

```powershell
cd F:\Matsim\matsim-example-project
.\.venv_geo311\Scripts\python.exe .\scripts\generate_matsim_multi_activity_agents.py
```

默认输入：

- WEDAN 工作通勤 OD：`data/worldcommuting_od/fuzhou/custom_features/fuzhou_city_23_greenspace_grid/CommutingODFlows/fuzhou_city_23_greenspace_grid/generation.npy`
- 新格网：`data/worldcommuting_od/fuzhou/custom_features/fuzhou_city_23_greenspace_grid/CityAndRegionSplit/fuzhou_city_23_greenspace_grid/regions.shp`
- WorldPop 总人口：`.../nfeat/worldpop.npy`
- WorldPop 年龄/性别人口：`.../nfeat/demos.npy`
- OSM POI：`data/osm/fuzhou/city_23/fuzhou_city_23_osm_pois.geojson`
- 距离矩阵：`.../adj/dis.npy`

默认输出：

```text
data/matsim_agents/fuzhou_city_23_greenspace_grid_multi_activity/
```

## 生成逻辑

新版不再把所有 agent 生成为 `h → w → h`。每个 home zone 先按 WorldPop 总人口分配 agent 数，再根据该 zone 的 `demos.npy` 年龄/性别结构抽样 agent 类型。

默认年龄规则：

- `student`：0–19 岁；
- `worker / non_worker_adult / family_worker`：20–64 岁；
- `retired`：65 岁及以上。

劳动年龄人口使用年龄-性别劳动参与率曲线拆分为 `worker` 与 `non_worker_adult`；`family_worker` 从 worker 中按该 zone 儿童占比二次抽样得到，不额外增加人口。

活动链模板包括：

- `worker`：`h → w → h`、`h → w → shop → h`、`h → w → leisure → h`、`h → w → restaurant → h`、`h → w → restaurant → w → h`
- `student`：`h → school → h`、`h → school → leisure → h`、`h → school → shop → h`
- `retired / non_worker_adult`：`h → shop → h`、`h → medical → h`、`h → leisure → h`、`h → shop → leisure → h`
- `family_worker`：`h → school → w → school → h`、`h → school → w → shop → school → h`、`h → w → school → leisure → h`

工作目的地优先使用 WEDAN off-diagonal OD；WEDAN 对角线不代表真实 intra-zone work flow，因此脚本用 `--intra-work-rate` 单独补估区内工作流。非工作活动目的地使用对应 POI 吸引力与距离衰减采样。

## 当前输出

一次默认运行生成：

- `plans_multi_activity.xml.gz`：MATSim `population_v6` plans；
- `zone_population_profile.csv`：每个 zone 的人口、年龄、性别画像；
- `agent_type_by_zone.csv`：每个 zone 的 agent 类型分布；
- `agent_age_sex_assignment_summary.csv`：年龄/性别到 agent 类型的分配摘要；
- `activity_chain_summary.csv`：活动链模板计数；
- `activity_points.geojson`：所有活动点，可在 QGIS 检查；
- `agent_activity_debug.csv`：每个 agent 的类型、模板、OD 方法和关键时间；
- `activity_od_summary.csv`：按活动类型统计的 OD 边；
- `multi_activity_agents_summary.json`：输入、输出、参数和校验摘要。

默认 30,000 agents 的当前校验结果：

```text
persons: 30000
bad_time_order: 0
activity types: h, w, school, shop, leisure, restaurant, medical
```

## 与 v1 的区别

v1 是通勤 baseline：

```text
h → w → h
```

v2 是多活动 synthetic population：

```text
WEDAN 工作 OD
+ WorldPop 年龄/性别分区人口结构
+ POI 活动吸引力
+ 距离衰减
+ 活动链模板
→ multi-activity MATSim plans
```

因此 v2 会自然产生上学、放学、下班购物、下班休闲、医疗等非通勤流量，更适合作为后续真实 MATSim 仿真与 reroute 的人口输入。
