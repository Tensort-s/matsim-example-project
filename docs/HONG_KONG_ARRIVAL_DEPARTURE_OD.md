# 香港 2026 一般工作日出入境 OD

## 1. 模型定位

本流程生成 2026 年一般工作日的香港出入境合成需求。入境处日统计决定口岸、方向和旅客类别的绝对边际；CBTS、TCS、HKTB 酒店统计、WorldPop、学校、工作吸引量和融合 POI 决定人群拆分、活动目的和香港内部空间分布。

结果不是观测到的“口岸 × 香港目的地”真实矩阵。正式输出必须描述为由官方边际、调查先验、空间吸引力和距离阻抗共同约束的合成 OD。

## 2. 数据口径

- 入境处日统计：使用 2026-01-01 至 2026-07-16。一般工作日排除周六、周日和政府公布的公众假期。
- 留出验证：仅用 1-6 月估计边际，并用 7 月非假日工作日检验；正式边际再使用全部可用日期重估。
- CBTS 2017：提供居于内地香港居民比例、目的和逗留结构先验，不提供 2026 绝对规模。
- TCS 2022/2023：提供酒店旅客与同日访客的机动化 trip rate、方式和时段结构。
- HKTB 2026 Q1：官方网页已确认最新期为 Jan-Mar 2026，但站点会话下载未能在自动流程中缓存 XLSX。未传入 `--hktb-purpose-xlsx` 时，程序保留并明确标记 CBTS/TCS 目的先验，不声称已抽取 Q1 单元格。
- 酒店统计 2026-05：使用 `P2` 的八区房间数与 `P4` 的五月入住率，权重为 `rooms × occupancy_rate`。

所有四份本地源表会复制到 `data/tourism/hongkong/raw/`，并在 `source_inventory.csv` 和 `source_checksums.json` 中记录路径、字节数和 SHA256。

## 3. 一般工作日边际

对每个方向和旅客类别，先计算每日类别总量中位数，再计算各口岸日份额中位数。口岸份额归一化后用最大余数法整数化，因此每个方向、类别和口岸的目标都是整数，且逐项回加等于类别总量。

14 个模型口岸与入境处统计分类一一对应。机场只使用 Terminal 1 坐标代表聚合机场节点；港口管制只使用 Harbour Control。Terminal 2 和 River Trade Terminal 只保留在位置审计层，不重复分配客流。

## 4. 人群与空间分配

香港居民在内地连接口岸按 CBTS 基准 `26.7%` 拆为居于内地香港居民，其余为通常居民。机场和海港的香港居民默认全部归入通常居民。通常居民只生成住宅格网与口岸之间的边境事件。

访客分为内地/其他和同日/过夜四类。内地访客过夜比例使用 37%，其他访客使用 66%。过夜访客以 3.1 晚、4.1 visitor-days 计；同日和过夜访客分别使用 2.51 和 2.48 次机动化出行/人日。

内部目的地权重包括：

- 观光和休闲：旅游、园林、体育、宗教、文化和餐饮 POI。
- 购物：零售及各类商店 POI。
- 商务：办公、金融、政府和 work-related POI。
- 探亲访友：校正 WorldPop 人口。
- 上学：教育局学校位置及估计容量。
- 上班：Census-scaled 工作 OD 的目的端吸引量与 work-related POI。
- 住宿：五月八个酒店地区的已入住客房容量；3% 人口权重作为亲友/住宅住宿回退。

口岸到目的格网采用目的吸引权重乘指数距离衰减。内部访客矩阵在 1,585 个格网间生成，并严格保持 TCS trip-rate 推导出的总机动化出行量。

## 5. 输出与单位

正式目录：

`data/tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday/`

主要文件：

- `arrival_bcp_to_grid.npy`：`(14, 1585)`，入境边境人次。
- `departure_grid_to_bcp.npy`：`(1585, 14)`，出境边境人次。
- `visitor_internal_grid_od.npy`：`(1585, 1585)`，访客在港机动化 trips。
- `synthetic_visitor_tours.parquet`：带权访客 cohort，不是逐人记录。
- `resident_border_events.parquet`：通常居民及居内地香港居民的独立边境事件。
- `border_internal_od_edges.parquet`：口岸与格网的长表边。
- `segmented_matrices/`：按边境类别、访客人群、目的、方式和时段保存的压缩矩阵。
- `matrix_manifest.json`：矩阵顺序、shape、单位和索引定义。
- `validation/`：边际守恒、18 区汇总、酒店权重和主要 POI 审计。
- `visualizations/`：一般工作日口岸流、18 区流、内部访客流、主要 POI 流和验证 PNG。

四种单位不能混用：

- `border passenger movements` 是入境处过关人次，不等于唯一人数。
- `weighted visitor cohorts` 是合成活动链的 cohort 权重。
- `visitor-days` 是访客人数乘在港天数。
- `internal mechanized trips` 是 visitor-days 乘 TCS trip rate。

## 6. 运行

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_preparation\prepare_hong_kong_arrival_departure_inputs.py `
  --data-root F:\Matsim\matsim-example-project\data

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_arrival_departure_od.py `
  --data-root F:\Matsim\matsim-example-project\data

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_arrival_departure_od.py `
  --data-root F:\Matsim\matsim-example-project\data --top-k 3000
```

如已取得 HKTB 官方 Q1 XLSX，可在第一条命令增加：

```text
--hktb-purpose-xlsx <local official xlsx>
```

## 7. 已知限制

- 没有观测到的口岸到具体活动点 OD，因此空间结果不能作为独立验证真值。
- 56 天代表日历用于显式报告重复工作日/周末边际造成的期初、期末存量差；它不是个体追踪数据。
- 酒店 POI 没有官方单店客房容量。地区总容量是官方约束，地区内分配仍是 POI 先验。
- 首版不覆盖公众假期、春节、黄金周、台风、大型会展或突发口岸管制。
- 首版不直接生成 MATSim `plans.xml.gz`。

## 8. 当前运行结果

2026-07-19 的完整运行得到：

- 一般工作日入境边境人次：`419,713`。
- 一般工作日出境边境人次：`420,208`。
- 访客内部机动化 trips：`750,005.5`，其中同日访客 `176,837.6`、过夜访客 `573,168.1`。
- 1-6 月拟合后对 7 月工作日的口岸 × 方向 × 类别 WAPE：`7.58%`。
- 14 × 1,585、1,585 × 14 和 1,585 × 1,585 三个主矩阵均为 finite、非负；内部矩阵对角线为零。
- 逐口岸 × 方向 × 类别最大守恒误差小于 `1e-9`。
- 人群、目的、方式和时段分层回加与总内部矩阵的最大差异小于 `1e-4`，差异来自 float32 累加。
