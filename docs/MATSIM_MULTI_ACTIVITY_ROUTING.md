# Multi-Activity Agents 路由与 MATSim 仿真

本文档记录从 multi-activity coordinate plans 生成 MATSim routed plans 的流程。

## 1. 生成 routed plans

```powershell
cd F:\Matsim\matsim-example-project
.\.venv_geo311\Scripts\python.exe .\scripts\generate_matsim_routes_from_multi_activity_plans.py
```

默认输入：

- `data/matsim_agents/fuzhou_city_23_greenspace_grid_multi_activity/plans_multi_activity.xml.gz`
- `data/osm/fuzhou_city_23/fuzhou_city_23_osm_roads.geojson`

默认输出：

```text
data/matsim_routes/fuzhou_city_23_greenspace_grid_multi_activity/
```

主要输出文件：

- `network.xml.gz`
- `routed_multi_activity_plans.xml.gz`
- `multi_activity_route_debug.csv`
- `unrouted_legs.csv`
- `unrouted_persons.csv`
- `multi_activity_route_generation_summary.json`

## 2. 当前路由结果

默认 30,000 agents 的当前结果：

```text
persons:       30,000
activities:   106,609
legs:          76,609
routed legs:   76,609
unrouted legs: 0
stuck agents in smoke test: 0
```

活动类型包括：

```text
h, w, school, shop, leisure, restaurant, medical
```

## 3. MATSim smoke test

```powershell
mvn exec:java `
  "-Dexec.mainClass=org.matsim.project.RunMatsimModelImplementation" `
  "-Dexec.args=run --config .\scenarios\fuzhou\config-multi-activity-smoke.xml --iterations=0 --output=output-fuzhou-multi-activity-smoke"
```

该 config 用于验证 MATSim 能读取 multi-activity network/plans，并生成 SimWrapper 默认 dashboard。

## 4. Reroute 仿真入口

短测试：

```powershell
mvn exec:java `
  "-Dexec.mainClass=org.matsim.project.RunMatsimModelImplementation" `
  "-Dexec.args=run --config .\scenarios\fuzhou\config-multi-activity-reroute.xml --iterations=10 --output=output-fuzhou-multi-activity-reroute-10"
```

正式仿真可把 `--iterations` 改为 `50`、`100` 或 `200`。

当前 reroute config 使用：

```text
BestScore              0.75
ReRoute                0.20
TimeAllocationMutator  0.05
```

含义是：大部分 agent 选择已有高分 plan，一部分 agent 重新规划 car route，少量 agent 调整活动结束时间。这样 multi-activity population 不只是固定路线执行，而能逐步对拥堵进行路径和时间层面的适应。

MATSim 2026 中关闭创新策略的参数名使用 `disableAfterIteration`。

50 轮正式测试：

```powershell
mvn exec:java `
  "-Dexec.mainClass=org.matsim.project.RunMatsimModelImplementation" `
  "-Dexec.args=run --config .\scenarios\fuzhou\config-multi-activity-reroute-50.xml --output=output-fuzhou-multi-activity-reroute-50"
```

50 轮配置采用前 40 轮允许 `ReRoute` 和 `TimeAllocationMutator`，第 41 轮起关闭创新策略，最后 10 轮用于稳定选择已有 plans。

仿真结束后生成小时交通量地图：

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\build_simwrapper_hourly_traffic_map.py --output-dir .\output-fuzhou-multi-activity-reroute-50
```

## 5. SimWrapper

仿真结束后打开：

```text
https://simwrapper.app
```

选择对应 output 文件夹，例如：

```text
F:\Matsim\matsim-example-project\output-fuzhou-multi-activity-smoke
```

或 reroute 输出目录。

如果需要按小时 link traffic map，可以复用：

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\build_simwrapper_hourly_traffic_map.py --output-dir .\output-fuzhou-multi-activity-smoke
```

## 6. 50 轮 reroute 实际运行记录

本地已完成一次 50 轮 multi-activity car-only reroute 仿真：

```text
config:    scenarios/fuzhou/config-multi-activity-reroute-50.xml
output:    output-fuzhou-multi-activity-reroute-50
persons:   30,000
trips:     76,609
stuck:     0
```

策略检查：

```text
Iteration 1-40:
  BestScore              0.75
  ReRoute                0.20
  TimeAllocationMutator  0.05

Iteration 41-50:
  ReRoute                0.00
  TimeAllocationMutator  0.00
```

日志中第 41 轮记录：

```text
RandomPlanSelector_TimeAllocationMutatorModule: oldWeight=0.05 newWeight=0.0
RandomPlanSelector_ReRoute: oldWeight=0.2 newWeight=0.0
```

结果检查：

```text
ITERATION 50 ENDS: yes
shutdown completed: yes
score last 10 iterations: stable around 124.925
hourly traffic peak: 16:00, total link entries 882,564
nonzero traffic hours: 06:00-23:00
```

SimWrapper 已生成默认 dashboard 与小时交通量地图：

```text
simwrapper-config.yaml
dashboard-1.yaml ... dashboard-5.yaml
analysis/traffic/traffic_stats_by_link_daily.csv
analysis/traffic/traffic_volume_by_link_hour.csv
analysis/traffic/traffic_volume_by_hour_summary.csv
viz-links-fuzhou-hourly-traffic.yaml
```
