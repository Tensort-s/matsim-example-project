# 香港 2026 一般工作日出入境 OD

## 1. 模型定位

本流程生成 2026 年一般工作日的香港出入境合成需求。入境处日统计决定口岸、方向和旅客类别的绝对边际；CBTS、TCS、HKTB 酒店统计、WorldPop、学校、工作吸引量和融合 POI 决定人群拆分、活动目的和香港内部空间分布。

结果不是观测到的“口岸 × 香港目的地”真实矩阵。正式输出必须描述为由官方边际、调查先验、空间吸引力和距离阻抗共同约束的合成 OD。

## 2. 数据口径

- 入境处日统计：使用 2026-01-01 至 2026-07-16。一般工作日排除周六、周日和政府公布的公众假期。
- 留出验证：仅用 1-6 月估计边际，并用 7 月非假日工作日检验；正式边际再使用全部可用日期重估。
- CBTS 2017：提供居于内地香港居民比例、目的和逗留结构先验，不提供 2026 绝对规模。
- TCS 2022/2023：提供酒店旅客与同日访客的机动化 trip rate、方式和时段结构。
- HKTB 2026 Q1：使用本地官方工作簿 `Visitor Arrival by Purpose of Visit 2026Q1.xlsx` 的 `Report` 页，分别提取内地访客和所有访客的过夜/同日目的结构。其他访客结构以“所有访客目的人数减内地访客目的人数”反推。
- 酒店统计 2026-05：使用 `P2` 的八区房间数与 `P4` 的五月入住率，权重为 `rooms × occupancy_rate`。

所有四份本地源表会复制到 `data/tourism/hongkong/raw/`，并在 `source_inventory.csv` 和 `source_checksums.json` 中记录路径、字节数和 SHA256。

## 3. 一般工作日边际

对每个方向和旅客类别，先计算每日类别总量中位数，再计算各口岸日份额中位数。口岸份额归一化后用最大余数法整数化，因此每个方向、类别和口岸的目标都是整数，且逐项回加等于类别总量。

14 个模型口岸与入境处统计分类一一对应。机场只使用 Terminal 1 坐标代表聚合机场节点；港口管制只使用 Harbour Control。Terminal 2 和 River Trade Terminal 只保留在位置审计层，不重复分配客流。

## 4. 人群与空间分配

香港居民在内地连接口岸按 CBTS 基准 `26.7%` 拆为居于内地香港居民，其余为通常居民。机场和海港的香港居民默认全部归入通常居民。通常居民只生成住宅格网与口岸之间的边境事件。

访客分为内地/其他和同日/过夜四类。内地访客过夜比例使用 HKTB Q1 的 `36.664%`，其他访客使用由总访客减内地访客反推的 `66.302%`。过夜访客以 3.1 晚、4.1 visitor-days 计；同日和过夜访客分别使用 2.51 和 2.48 次机动化出行/人日。

HKTB Q1 的官方目的类别为 `Vacation / Business / Visiting Friends or Relatives / En Route & Others`。模型严格保持每个市场和逗留类型的四类官方比例，只在官方聚合类别内部使用历史先验细分：

- 其他访客的 `Vacation` 按 TCS 先验拆为 sightseeing、leisure 和 shopping。
- 内地访客的 `En Route & Others` 按 CBTS 先验拆为 transit、other 和 work。
- 其他访客的 `En Route & Others` 按 TCS 先验拆为 transit 和 other。

因此 2026 Q1 决定一级目的结构，CBTS/TCS 不再决定一级占比，只负责模型所需的聚合项内部细分。

内部目的地权重包括：

- 观光和休闲：旅游、园林、体育、宗教、文化和餐饮 POI。
- 购物：零售及各类商店 POI。
- 商务：办公、金融、政府和 work-related POI。
- 探亲访友：校正 WorldPop 人口。
- 上学：教育局学校位置及估计容量。
- 上班：当前 WEDAN/LSUG `generation_hk_census_projected.npy` 的目的端吸引量与 work-related POI。
- 住宿：五月八个酒店地区的已入住客房容量；3% 人口权重作为亲友/住宅住宿回退。

工作吸引量只使用工作 OD 的目的端列和，不重新生成固定通勤需求。当前正式来源为
`data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/CommutingODFlows/hong_kong_fixed_link_grid/hk_scaler_calibration_v1/final/generation_hk_census_projected.npy`。
早期 `generation_2021_census_area_scaled.npy` 和 global-unit scaling 输出仅是 Census 约束诊断/历史比较产物，不作为 V1 或 V2 口岸 OD 的默认输入。

口岸到目的格网采用目的吸引权重乘指数距离衰减。内部访客矩阵在 1,585 个格网间生成，并严格保持 TCS trip-rate 推导出的总机动化出行量。

## 5. 输出与单位

历史 V1（欧氏距离）基线目录：

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
- `validation/`：边际守恒、18 区—口岸汇总、酒店权重和游客活动链审计。
- `prepared_inputs/hktb_2026_q1_purpose_by_market_stay.csv`：四组 HKTB 官方/反推目的比例。
- `validation/purpose_priors_used.csv`：实际进入 OD 生成器的最终目的先验。
- `visualizations/hong_kong_typical_weekday_dc18_control_point_od_flows.png`：抵港和离港分别聚合到 18 区与 14 个模型口岸的 Top 100 有向流。
- `visualizations/hong_kong_visitor_arrival_activity_chains_top100.png`：Top 100 带权抵港 cohort 的多路径点活动链。
- `validation/visitor_arrival_activity_chains_top100.csv/.geojson`：活动链使用的口岸、住宿点、主要活动 POI、次要活动 POI 和路径审计。

四种单位不能混用：

- `border passenger movements` 是入境处过关人次，不等于唯一人数。
- `weighted visitor cohorts` 是合成活动链的 cohort 权重。
- `visitor-days` 是访客人数乘在港天数。
- `internal mechanized trips` 是 visitor-days 乘 TCS trip rate。

## 6. 运行

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_preparation\prepare_hong_kong_arrival_departure_inputs.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --hktb-purpose-xlsx "F:\Matsim\matsim-example-project\data\tourism\hongkong\raw\Visitor Arrival by Purpose of Visit 2026Q1.xlsx"

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_arrival_departure_od.py `
  --data-root F:\Matsim\matsim-example-project\data

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_arrival_departure_od.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --top-district-flows 100 --top-activity-chains 100
```

## 7. 已知限制

- 没有观测到的口岸到具体活动点 OD，因此空间结果不能作为独立验证真值。
- 56 天代表日历用于显式报告重复工作日/周末边际造成的期初、期末存量差；它不是个体追踪数据。
- 酒店 POI 没有官方单店客房容量。地区总容量是官方约束，地区内分配仍是 POI 先验。
- Top 100 活动链是根据带权访客 cohort 和 integrated POI 构造的代表性多点链，不是观测轨迹；即日链为“口岸—主要活动—次要活动”，过夜链额外包含住宿路径点。
- 首版不覆盖公众假期、春节、黄金周、台风、大型会展或突发口岸管制。
- 首版不直接生成 MATSim `plans.xml.gz`。

## 8. 当前运行结果

2026-07-20 的完整运行得到：

- 一般工作日入境边境人次：`419,713`。
- 一般工作日出境边境人次：`420,208`。
- 访客内部机动化 trips：`748,333.0`，其中同日访客 `177,385.8`、过夜访客 `570,947.3`。
- 1-6 月拟合后对 7 月工作日的口岸 × 方向 × 类别 WAPE：`7.58%`。
- 14 × 1,585、1,585 × 14 和 1,585 × 1,585 三个主矩阵均为 finite、非负；内部矩阵对角线为零。
- 逐口岸 × 方向 × 类别最大守恒误差为 `7.28e-12` 人次。
- 人群、目的、方式和时段分层回加与总内部矩阵的最大差异小于 `1e-4`，差异来自 float32 累加。
- 18 区—口岸图每个方向显示 Top 100 流，分别覆盖抵港总量的 `88.1%` 和离港总量的 `87.9%`。
- Top 100 游客抵港活动链共 `37` 条过夜链和 `63` 条即日链，覆盖抵港访客 cohort 权重的 `2.82%`。

## 9. 公共交通可达性 V2

旧版使用“口岸到每个目的格网的欧氏距离衰减”，并在构造后续活动时继续继承该口岸条件，因而会把深圳湾、香园围等口岸附近的郊区 POI 赋予过高权重。V2 保留旧目录作为历史基准，新结果写入：

`data/tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday_pt_access_v2/`

V2 使用建成的 MATSim 道路和公共交通供给，通过 SwissRailRaptor 计算 `07:00/10:00/13:00/17:00/20:00/22:00` 六时段、`1,585` 个格网加 `14` 个口岸的时刻表 skim。广义时间采用车内时间 `1.0`、候车和步行 `2.0`、每次换乘 `300 s`；无公共交通路径保存为不可达，不使用欧氏距离替代。

距离衰减参数使用“酒店/住宿地到在港活动点”的公共交通时间校准，使加权平均值为 TCS 酒店旅客约 `41 min`。口岸到首次活动及最后活动到口岸只使用该参数的 `0.1` 倍，避免把边境接驳阻抗误当作旅客对香港核心目的地的强烈排斥；这两类边境腿仍只使用真实公共交通可达路径，不回退到直线距离。

空间分配分为两层：

- 首次入境落点使用口岸、时段、目的吸引力和公共交通广义时间。
- 住宿后的主要活动、主要活动后的次要活动只使用住宿地或上一活动点，不再引用入境口岸。

内地即日访客使用 CBTS 2017 六区多选到访率。六区比例是“旅客是否到访该区”的 incidence，合计可超过 100%，不是互斥目的地区边际；V2 在一至两个活动点的链模板中匹配该 incidence。18 区仅用于目的相关的区内细分先验。口岸 × 方向 × 类别、HKTB Q1 目的结构和酒店八区结构仍为硬约束。

新增表包括 `synthetic_visitor_activities.parquet` 和 `synthetic_visitor_legs.parquet`。前者保存有序住宿、主要和次要活动点，优先使用 integrated POI 的真实坐标；后者明确区分边境人次权重和内部活动转移权重。兼容的三个主矩阵文件名保持不变，但必须从 V2 目录读取。

运行顺序：

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_pt_generalized_time_skims.py `
  --data-root F:\Matsim\matsim-example-project\data

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_arrival_departure_od_pt_access_v2.py `
  --data-root F:\Matsim\matsim-example-project\data

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_arrival_departure_od_pt_access_v2.py `
  --data-root F:\Matsim\matsim-example-project\data
```

当前正式运行结果：

- skim shape 为 `(6, 1599, 1599)`，时刻表 OD 组合可达率为 `41.61%`；不可达组合保留为不可达。
- 一般工作日抵港和离港边境人次分别为 `419,713` 和 `420,208`，与 V1 的入境处边际一致。
- 访客内部机动化 trips 为 `748,333.0`；三个主矩阵均 finite、非负，内部矩阵对角线为零。
- 逐口岸 × 方向 × 类别最大守恒误差为 `1.13e-10` 人次。
- 内地即日访客 CBTS 六区 incidence 最大误差为 `0.933` 个百分点，低于 `2` 个百分点阈值。
- HKTB Q1 人群 × 停留 × 目的比例逐项匹配；酒店八区份额最大误差为 `5.55e-17`。
- 与 V1 相比，距口岸 `3/5/10 km` 内的活动占比分别由 `3.68/9.07/29.22%` 降为 `2.84/5.31/13.88%`。
- 人群、停留、目的、方式和时段矩阵回加到总矩阵的最大逐格差异不超过 `1.61e-4`，属于 `float32` 保存误差。

V2 没有改变一般工作日口岸边际估计，因此 1-6 月拟合、7 月工作日留出的口岸 × 方向 × 类别 WAPE 仍为 V1 的 `7.58%`。这项指标验证的是边际预测，不用于证明口岸到具体活动点的空间 OD 准确性。
