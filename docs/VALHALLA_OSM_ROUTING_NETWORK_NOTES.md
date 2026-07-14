# 论文 2606.00430v1 中 Valhalla/OSM 可路径规划网络方法笔记

论文：`SF-LIFE: A Large-Scale Simulated Movement Dataset for the San Francisco Bay Area`

本笔记聚焦论文如何把 OSM 路网转换成 Valhalla 可路径规划网络，以及这套流程如何迁移到福州 Greenspace/MATSim 项目。

## 1. 论文中的核心思路

论文中的仿真链条是：

```text
OSM roads + buildings + GTFS
        ↓
构建仿真环境：建筑物、道路、公交/轨道
        ↓
agent agenda：每天要去哪些建筑、何时出发、使用什么交通方式
        ↓
Valhalla multi-mode routing
        ↓
完整轨迹：步行、自行车、汽车、公交、轨道等多模式路径
```

其中 OSM 的作用有两类：

1. 建筑与 POI：给 agent 的 home/work/school/restaurant 等活动地点提供空间锚点；
2. 道路网络：作为 Valhalla 的可路径规划图，约束 agent 的真实移动轨迹。

## 2. OSM 路网到 Valhalla 路径网络

论文明确说，OSM road network 会被 Valhalla 的 Mjolnir 工具转换成可路径规划的 tiles。

Valhalla/Mjolnir 的功能可以理解为：

```text
OSM PBF / OSM extract
        ↓
解析 OSM ways/nodes/tags
        ↓
清理道路属性、通行权限、速度、方向、转向等
        ↓
切分成分层 graph tiles
        ↓
Valhalla routing service 读取 tiles 做路径规划
```

Valhalla 官方文档也说明，Mjolnir 负责解析 OSM extracts、切割 routable graph tiles、生成 tile hierarchy，并检查数据缺陷。

## 3. 论文提到的额外网络修复

论文不是简单把 OSM 丢给 Valhalla。它还提到两个关键修复：

1. 将 origin/destination buildings 映射到最近道路点；
2. 对 OSM road network 做连通性处理：
   - 连接位置几乎相同但拓扑未连上的顶点；
   - 移除不连通的网络部分；
   - 得到 fully connected version 的 OSM road network。

这一步很重要，因为 agent 的 home/work/school 等点来自建筑 centroid，如果建筑点无法被正确吸附到路网，Valhalla 路径规划会失败或产生绕路。

## 4. 如果加公共交通：OSM + GTFS 融合

论文中的 SF-LIFE 使用了 40+ transit agencies 的 GTFS 数据。其流程是：

```text
GTFS schedules/routes/stops
        ↓
valhalla_build_transit 生成 transit tiles
        ↓
valhalla_build_tiles 时把 transit graph 连接到 OSM road graph
        ↓
Valhalla 支持公交/轨道/步行换乘路径
```

对我们当前福州项目而言，除非后续拿到福州公交/地铁 GTFS 或 GTFS-like 数据，否则可以先只做 OSM road routing，不启用 transit。

## 5. Valhalla 官方推荐构图命令骨架

官方 Mjolnir guide 的基础流程是：

```bash
valhalla_build_config > valhalla.json
valhalla_build_tiles --config /path/to/valhalla.json /data/osm_extract.pbf
```

常见可选数据：

```text
admins      → valhalla_build_admins
timezones   → valhalla_build_timezones
elevation   → valhalla_build_elevation
transit     → valhalla_build_transit + valhalla_build_tiles
```

最小可用版本只需要：

```text
OSM PBF + valhalla.json + valhalla_build_tiles
```

## 6. 迁移到福州 Greenspace 项目的建议流程

当前我们已经有：

```text
data/osm/fuzhou/city_23/fujian-latest.osm.pbf
data/osm/fuzhou/city_23/city_23.osm.pbf
data/osm/fuzhou/city_23/fuzhou_city_23_boundary.geojson
```

建议不要直接用 road-only 的 `city_23.osm.pbf` 构 Valhalla tiles。Valhalla 更适合吃完整 OSM PBF，因为它需要道路、节点、限制、access tags、可能的边界/关系信息。推荐使用 `fujian-latest.osm.pbf`，或用 osmium 按 Greenspace 福州边界从福建 PBF 裁剪出完整 extract。

推荐流程：

```text
1. 用 Greenspace 福州边界裁剪完整 OSM PBF
2. 可选：做网络连通性检查和小断点修复
3. 生成 valhalla.json
4. valhalla_build_tiles 构建 graph tiles
5. 启动 valhalla_service
6. 用 /route 或 Python actor 测试 home/work OD 路径
7. 将路径 polyline 或分段 travel time 用于 MATSim agent OD / route 初始化
```

## 7. 与 MATSim 的衔接方式

Valhalla 与 MATSim 的角色不同：

```text
Valhalla:
  从真实 OSM 网络上给 OD 点求路径、时间、距离、多模式路线。

MATSim:
  在交通仿真网络上运行 agent、拥堵、重规划、出行计划演化。
```

可选衔接方式有三种：

1. 只用 Valhalla 生成 OD 间距离/时间矩阵，MATSim 自己路由；
2. 用 Valhalla 生成初始 route polyline，再 map-match/转换到 MATSim links；
3. 直接把 OSM 转 MATSim network，同时另建 Valhalla tiles，用二者互相校验。

对当前项目，我建议先做第 1 种：用 Valhalla 得到每个 OD 对的距离、时间和可达性，作为 OD 生成和活动点抽样的约束。这样风险最低。

## 8. 关键注意事项

- OSM extract 要尽量完整，不要只保留 roads，否则 Valhalla 可能缺 access、relation、turn restriction 等信息。
- 建筑 centroid 不一定在道路上，必须做 nearest road snapping。
- 城市边界裁剪太紧会导致边界附近路径断裂，最好给福州边界加 buffer 后构图。
- 如果需要公交/地铁，需要 GTFS；没有 GTFS 时先不要假装有 transit。
- 论文中强调 fully connected road network，这对批量 agent 路由非常关键。
- Valhalla tiles 是服务端路径规划格式，不是 MATSim network XML；二者需要另做转换或联动。

