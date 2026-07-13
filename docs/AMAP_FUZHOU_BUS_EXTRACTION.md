# 高德福州公交数据抓取

脚本：

```text
scripts/fetch_fuzhou_bus_from_amap.py
```

目标：从高德 Web Service 公交线路查询接口批量抓取福州公交线路、站点、上下站关系、运营时间、发车间隔和可选线路轨迹。

## 1. 重要限制

高德公开 Web Service 没有提供“下载某城市全部公交线路”的单一接口。公交线路查询必须给关键词，因此脚本采用：

```text
关键词枚举
  -> 请求 bus/linename
  -> 按高德 line_id 去重
  -> 展开线路-站点序列
  -> 解析 timedesc 发车间隔
```

因此，全量结果取决于关键词覆盖范围。建议先 pilot，确认数据结构后再跑 citywide。

## 2. API Key

不要把 key 写入项目文件。PowerShell 中设置：

```powershell
$env:AMAP_WEB_KEY="你的高德Web服务Key"
```

## 3. 小规模试抓

```powershell
cd F:\Matsim\matsim-example-project

.\.venv_geo311\Scripts\python.exe .\scripts\fetch_fuzhou_bus_from_amap.py `
  --keyword-profile pilot `
  --include-polyline `
  --output-dir .\data\transit\fuzhou_bus_amap_pilot `
  --sleep 3 `
  --pages 2 `
  --offset 20
```

## 4. 自定义关键词

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\fetch_fuzhou_bus_from_amap.py `
  --keywords "K1路,51路,101路,夜班2号线,地铁接驳1号专线" `
  --include-polyline `
  --output-dir .\data\transit\fuzhou_bus_amap_custom
```

或用文本文件：

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\fetch_fuzhou_bus_from_amap.py `
  --keywords-file .\data\transit\fuzhou_bus_keywords.txt `
  --include-polyline `
  --output-dir .\data\transit\fuzhou_bus_amap_custom
```

## 5. 较大范围抓取

数字线路枚举：

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\fetch_fuzhou_bus_from_amap.py `
  --keyword-profile numeric `
  --max-number 400 `
  --include-polyline `
  --output-dir .\data\transit\fuzhou_bus_amap_numeric_400 `
  --sleep 3 `
  --pages 2 `
  --offset 20
```

更宽的 citywide profile 会额外枚举 K 线、夜班线、地铁接驳线、马尾快线、闽侯/长乐相关线路等：

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\fetch_fuzhou_bus_from_amap.py `
  --keyword-profile citywide `
  --max-number 400 `
  --include-polyline `
  --output-dir .\data\transit\fuzhou_bus_amap_citywide_400 `
  --sleep 3 `
  --pages 2 `
  --offset 20
```

注意：citywide 抓取请求数较多，可能受到高德 key 的 QPS 或日配额限制。脚本已对 `CUQPS_HAS_EXCEEDED_THE_LIMIT` 做退避重试，但不能绕过日配额。

如果触发：

```text
USER_DAILY_QUERY_OVER_LIMIT
```

说明当日请求额度已用完。新版脚本会停止继续请求，并尽量保存已抓取的部分结果，同时写出：

```text
amap_api_errors.json
amap_bus_fetch_summary.json
```

第二天可以缩小关键词范围继续抓，或提高高德应用的日配额。

## 5.1 先发现线路名，再调用高德

参考 `capsule-8584249` 的思路，可以先从外部线路目录获取线路名，再逐条调用高德 `bus/linename`。脚本现在支持两个发现源：

### 8684 发现

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\fetch_fuzhou_bus_from_amap.py `
  --discover-from-8684 `
  --8684-city-slug fuzhou `
  --discovery-only `
  --output-dir .\data\transit\fuzhou_bus_amap_8684_discovery
```

注意：当前 `https://fuzhou.8684.cn/list1` 已不再返回旧版公交线路目录，而是普通资讯页面。因此福州 8684 发现目前不可用。脚本会写出 `keyword_discovery_diagnostics.json` 记录页面状态。

### Wikipedia 线路表发现

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\fetch_fuzhou_bus_from_amap.py `
  --discover-from-wikipedia `
  --discovery-only `
  --output-dir .\data\transit\fuzhou_bus_amap_wikipedia_discovery
```

当前测试可发现约 334 条福州公交线路名。

用发现到的线路名调用高德：

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\fetch_fuzhou_bus_from_amap.py `
  --discover-from-wikipedia `
  --max-keywords 30 `
  --include-polyline `
  --output-dir .\data\transit\fuzhou_bus_amap_wikipedia_30 `
  --sleep 3 `
  --pages 1 `
  --offset 20
```

如果需要从中间继续，可用：

```powershell
--start-keyword-index 31
```

## 6. 输出文件

| 文件 | 说明 |
|---|---|
| `amap_bus_lines.csv` | 线路/方向记录，包含线路名、类型、首末站、首末班、距离、票价、是否有轨迹 |
| `amap_bus_stops_by_line.csv` | 线路-站点展开表，一行是某条线路某方向上的一个站点 |
| `amap_bus_stations.csv` | 去重公交站点表 |
| `amap_bus_adjacent_stop_edges.csv` | 上下站关系表 |
| `amap_bus_service_frequency.csv` | 从高德 `timedesc` 解析出的分时段发车间隔 |
| `amap_bus_data_coverage_and_missing_items.csv` | 每条线路的数据覆盖与缺失情况 |
| `amap_bus_stations.geojson` | 站点点图层 |
| `amap_bus_stops_by_line.geojson` | 按线路展开的站点点图层 |
| `amap_bus_adjacent_stop_edges.geojson` | 上下站连线，不是真实线路轨迹 |
| `amap_bus_line_trajectories.geojson` | 可选，高德返回的线路 polyline 轨迹 |
| `amap_bus_fetch_summary.json` | 抓取摘要 |
| `keywords_used.txt` | 本次使用的关键词 |
| `amap_api_errors.json` | 如果发生 API 错误或日配额耗尽，记录错误关键词和 infocode |

## 7. 坐标系提醒

高德返回坐标通常是 GCJ-02。接入 MATSim 前需要：

```text
GCJ-02 -> WGS84 -> EPSG:32650
```

## 8. 和地铁数据的关系

脚本默认排除 `line_type` 中包含 `地铁` 的线路。如果希望公交和地铁混合抓取，可加：

```powershell
--include-metro
```

但用于 MATSim 时，建议公交和地铁分别建 schedule，再合并为公共交通网络。
