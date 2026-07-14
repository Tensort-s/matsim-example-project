# 高德福州地铁数据抓取脚本

> Legacy/provenance note: this document records an earlier experiment or data collection path. For the current active Fuzhou workflow and paths, read `docs/PROJECT_ONBOARDING.md` first.

本脚本用于从高德 Web Service 公交线路查询接口抓取福州地铁相关信息，并整理成后续构建 MATSim `transitSchedule.xml.gz` 所需的中间数据。

脚本：

```text
scripts/fetch_fuzhou_metro_from_amap.py
```

默认输出目录：

```text
data/transit/fuzhou/metro_amap/
```

## 1. 数据范围

脚本默认查询：

```text
福州地铁1号线
福州地铁2号线
福州地铁4号线
福州地铁5号线
福州地铁6号线
福州地铁滨海快线
滨海快线
福州地铁F1线
```

抓取并整理：

- 地铁站点位置；
- 所属线路；
- 单条线路方向；
- 站点顺序；
- 上下站关系；
- 首末班或运营时间字段；
- 可选：高德返回的线路 `polyline` 轨迹。

注意：高德公交线路接口通常返回首末班时间，但不稳定返回“发车间隔/班次间隔”。因此脚本会生成 `amap_metro_service_frequency.csv`，其中 `headway_minutes` 默认留空，`headway_source` 标记为 `not_returned_by_amap_busline_api`，后续可用官方运营资料人工补齐。

## 2. API Key

不要把 key 写入仓库。推荐在 PowerShell 中设置环境变量：

```powershell
$env:AMAP_WEB_KEY="你的高德Web服务Key"
```

也可以运行时传入：

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\fuzhou_single_city\data_acquisition\fetch_fuzhou_metro_from_amap.py --key "你的高德Web服务Key"
```

## 3. 不抓线路轨迹，只抓站点和上下站关系

```powershell
cd F:\Matsim\matsim-example-project

.\.venv_geo311\Scripts\python.exe .\scripts\fuzhou_single_city\data_acquisition\fetch_fuzhou_metro_from_amap.py `
  --city 福州 `
  --output-dir .\data\transit\fuzhou\legacy\metro_amap
```

这个模式下，脚本会删除原始响应中的 `polyline` 字段，并输出：

```text
amap_raw_busline_responses_no_polyline.json
```

## 4. 抓取线路轨迹

如果需要保留高德返回的线路轨迹，加入 `--include-polyline`：

```powershell
cd F:\Matsim\matsim-example-project

.\.venv_geo311\Scripts\python.exe .\scripts\fuzhou_single_city\data_acquisition\fetch_fuzhou_metro_from_amap.py `
  --city 福州 `
  --include-polyline `
  --output-dir .\data\transit\fuzhou\legacy\metro_amap
```

会额外生成：

```text
amap_metro_line_trajectories.geojson
amap_raw_busline_responses_with_polyline.json
```

## 4.1 当前运营线路版本

如果只保留当前运营线路，可使用：

```powershell
cd F:\Matsim\matsim-example-project

$env:AMAP_WEB_KEY="你的高德Web服务Key"

.\.venv_geo311\Scripts\python.exe .\scripts\fuzhou_single_city\data_acquisition\fetch_fuzhou_metro_from_amap.py `
  --city 福州 `
  --include-polyline `
  --active-only `
  --exclude-name-regex "东延|东调" `
  --output-dir .\data\transit\fuzhou\legacy\metro_amap_active `
  --sleep 3 `
  --pages 1 `
  --offset 20 `
  --max-retries 5
```

这会剔除高德返回的 `status != 1` 线路，并排除名称包含 `东延`、`东调` 的建设中线路。

当前已确认：

```text
地铁2号线东延线一期/二期：建设中，不进入当前运营版本
地铁6号线东调段：建设中，不进入当前运营版本
```

当前运营版本输出在：

```text
data/transit/fuzhou/metro_amap_active/
```

## 5. 输出文件

| 文件 | 说明 |
|---|---|
| `amap_metro_lines.csv` | 线路记录，包括线路名、方向、首末班、距离、票价、是否有 polyline |
| `amap_metro_stops_by_line.csv` | 线路-站点展开表，一行是某条线路某个方向上的一个站点 |
| `amap_metro_stations.csv` | 去重后的站点表 |
| `amap_metro_adjacent_stop_edges.csv` | 上下站关系表，可用于构建 transit route stop sequence |
| `amap_metro_service_frequency.csv` | 运营时间和发车间隔占位表 |
| `amap_metro_stations.geojson` | 去重站点点图层 |
| `amap_metro_stops_by_line.geojson` | 按线路方向展开的站点点图层 |
| `amap_metro_adjacent_stop_edges.geojson` | 相邻站点连线，注意这是站间直连线，不是轨道真实轨迹 |
| `amap_metro_line_trajectories.geojson` | 可选，高德返回的线路 polyline 轨迹 |
| `amap_metro_fetch_summary.json` | 抓取摘要 |

当前运营版本中还包含：

| 文件 | 说明 |
|---|---|
| `manual_headway_observations.csv` | 从高德手机版站点详情等来源手动记录的到站/下一班观测 |
| `amap_metro_service_frequency_with_manual_observations.csv` | 高德 `timedesc` 解析结果 + 手动观测合并表 |
| `amap_metro_active_data_coverage_and_missing_items.csv` | 当前运营线路的数据覆盖与缺失清单 |

## 6. 自定义查询关键词

可以用逗号分隔：

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\fuzhou_single_city\data_acquisition\fetch_fuzhou_metro_from_amap.py `
  --keywords "福州地铁1号线,福州地铁2号线,滨海快线"
```

也可以用 UTF-8 文本文件：

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\fuzhou_single_city\data_acquisition\fetch_fuzhou_metro_from_amap.py `
  --keywords-file .\data\transit\fuzhou\legacy\metro_amap\keywords.txt
```

## 7. 后续用于 MATSim 的建议

生成 MATSim 地铁 schedule 时，优先使用：

```text
amap_metro_stations.csv
amap_metro_adjacent_stop_edges.csv
amap_metro_lines.csv
amap_metro_service_frequency.csv
```

如果 `--include-polyline` 已开启，可以用：

```text
amap_metro_line_trajectories.geojson
```

作为 transit route 几何参考。但真正的 MATSim transit route 仍需要后续转换为：

```text
transitSchedule_metro.xml.gz
transitVehicles_metro.xml.gz
```

并与 MATSim network 进行 stop/link 映射。

## 8. 坐标系提醒

高德 Web Service 返回的经纬度通常是 GCJ-02 坐标，不是 OSM/WGS84，也不是当前福州 MATSim 使用的 `EPSG:32650`。

因此，在接入 MATSim 前建议增加一步：

```text
AMap GCJ-02 lon/lat
  -> WGS84 lon/lat
  -> EPSG:32650
```

否则站点与 OSM 路网/地铁轨道会有几十到数百米偏移。

## 9. 关于高德手机版“下一班”信息

高德手机版的地铁站详情页可能显示“即将进站”“下一班 8 分钟”等实时或准实时信息。公开 Web Service POI 详情接口目前没有稳定返回该字段，因此脚本采用手动观测表方式接入。

示例：

```text
manual_headway_observations.csv
```

字段包括：

```text
observed_date
observed_time
station_name
line_name
direction_to
current_train_status
next_train_minutes
estimated_headway_minutes
confidence
notes
```

这类观测适合用于补缺，例如 6 号线、滨海快线缺少 `timedesc` 发车间隔时，可以在早高峰、平峰、晚高峰、夜间分别采样若干站点和方向，再汇总为 MATSim 使用的分时段 headway。

注意：单次“下一班 N 分钟”不是完整运营图。它只代表某一时刻、某一站点、某一方向的观测，应标记来源和置信度，避免当作全天固定发车间隔。
