# 高德手机版地铁到站信息半自动采样

> Legacy/provenance note: this document records an earlier experiment or data collection path. For the current active Fuzhou workflow and paths, read `docs/PROJECT_ONBOARDING.md` first.

脚本：

```text
scripts/collect_amap_mobile_metro_arrivals.py
```

目标：通过 Android 手机上的高德 App 页面，采样“即将进站 / 下一班 N 分钟 / 首末班”等可见信息，并保存截图、UI 文本和 CSV 观测表。

这个脚本不调用高德私有接口，只做：

```text
ADB 打开/搜索高德 App 页面
截图
uiautomator dump 可见 UI 文本
正则解析下一班、首末班、方向等信息
```

## 1. 准备条件

电脑需要安装 Android Platform Tools，并能运行：

```powershell
adb devices
```

手机需要：

- 安装高德地图 App；
- 开启开发者选项；
- 开启 USB 调试；
- 连接电脑后允许 USB 调试授权；
- 手机保持解锁状态。

如果 `adb.exe` 没有加入 PATH，可以运行脚本时传入：

```powershell
--adb "C:\path\to\platform-tools\adb.exe"
```

## 2. 生成默认采样目标

默认目标覆盖当前缺发车间隔的线路/方向：

```text
6号线：潘墩 -> 万寿
6号线：万寿 -> 潘墩
滨海快线：福州火车站 -> 文岭
滨海快线：文岭 -> 福州火车站
```

生成目标 CSV：

```powershell
cd F:\Matsim\matsim-example-project

.\.venv_geo311\Scripts\python.exe .\scripts\fuzhou_single_city\data_acquisition\collect_amap_mobile_metro_arrivals.py `
  --write-default-targets .\data\transit\fuzhou\legacy\metro_amap_mobile_observations\targets.csv
```

可手动编辑：

```text
data/transit/fuzhou/metro_amap_mobile_observations/targets.csv
```

## 3. 推荐模式：手动导航 + 自动截图识别

因为高德 App 不同版本的 URI 跳转行为不完全一致，最稳的是手动打开站点详情页，然后让脚本截图和解析。

```powershell
cd F:\Matsim\matsim-example-project

.\.venv_geo311\Scripts\python.exe .\scripts\fuzhou_single_city\data_acquisition\collect_amap_mobile_metro_arrivals.py `
  --manual `
  --targets .\data\transit\fuzhou\legacy\metro_amap_mobile_observations\targets.csv `
  --output-dir .\data\transit\fuzhou\legacy\metro_amap_mobile_observations
```

每个目标开始时，脚本会暂停。你在手机上打开对应高德地铁站详情页，确认页面能看到“下一班 N 分钟”等信息后，按回车，脚本会保存：

```text
screenshots/*.png
ui_xml/*.xml
ui_text/*.txt
amap_mobile_metro_arrival_observations.csv
```

## 4. 尝试自动打开高德搜索页

可以尝试：

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\fuzhou_single_city\data_acquisition\collect_amap_mobile_metro_arrivals.py `
  --open-method auto `
  --targets .\data\transit\fuzhou\legacy\metro_amap_mobile_observations\targets.csv `
  --output-dir .\data\transit\fuzhou\legacy\metro_amap_mobile_observations
```

如果高德 URI 跳转失败，脚本会提示手动导航后再截图。

也可只启动高德，不尝试搜索：

```powershell
--open-method monkey
```

或完全不打开 App，只采当前屏幕：

```powershell
--open-method none --manual
```

## 5. 重复采样

例如对每个目标每隔 10 分钟采样 3 次：

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\fuzhou_single_city\data_acquisition\collect_amap_mobile_metro_arrivals.py `
  --manual `
  --targets .\data\transit\fuzhou\legacy\metro_amap_mobile_observations\targets.csv `
  --repeat 3 `
  --interval-seconds 600 `
  --output-dir .\data\transit\fuzhou\legacy\metro_amap_mobile_observations
```

## 6. 输出字段

`amap_mobile_metro_arrival_observations.csv` 包含：

```text
captured_at
station_name
line_name
direction_to
current_train_status
next_train_minutes
estimated_headway_minutes
first_train_time
last_train_time
parsed_line_name
parsed_direction_to
parse_confidence
needs_manual_review
screenshot_path
ui_xml_path
ui_text_path
```

如果 `needs_manual_review=true`，说明页面文本没有被 UIAutomator 清楚读取，建议打开对应截图人工校对。

## 7. 使用建议

单次“下一班 N 分钟”不是完整时刻表。建议对 6 号线和滨海快线按以下时段采样：

```text
早高峰：07:30-08:30
平峰：10:00-11:00
晚高峰：17:30-18:30
夜间：21:30-22:30
```

每个方向至少采样 2-3 次。最终用于 MATSim 时，建议把同一时段的观测取中位数作为 headway，并标记来源为：

```text
amap_mobile_visible_observation
```

## 8. 隐私和可复现性

截图会保存到本地项目目录，可能包含手机状态栏、定位状态或其他 UI 元素。不要把截图直接公开上传。CSV 中会保存截图路径和 UI 文本，便于后续审计。
