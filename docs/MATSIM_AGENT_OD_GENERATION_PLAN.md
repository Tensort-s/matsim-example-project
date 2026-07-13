# 面向 MATSim Input 的 Agent OD 生成方案

本文档基于项目内抽取的论文文本与 WEDAN 补充材料整理：

- `docs/pdf-text/s41597-026-07279-z_reference.txt`
- `docs/pdf-text/41597_2026_7279_MOESM1_ESM.txt`

目标是把“区域级通勤 OD 矩阵”转换成 MATSim 可运行的 agent-based daily plans，主要输出 `plans.xml.gz`，并可选输出 `facilities.xml.gz`、区域索引和校验表。

## 1. 论文与 WEDAN 对 MATSim 的启发

论文的数据构建逻辑可以简化成三层：

1. 城市边界与区域划分：先确定城市边界，再用自适应网格把城市切成若干区域。网格尺寸随城市尺度变化，论文中采用约 5% 城市边界尺度，并限制在 500 m 到 5 km 之间。
2. 区域画像：每个区域提取人口/年龄性别结构、遥感语义特征和 POI 类别计数，作为区域节点特征。
3. OD 生成：WEDAN 把城市看作带属性的有向加权图。区域是节点，区域间通勤流是有向边，边权 `F_ij` 表示居住在区域 `i`、工作在区域 `j` 的人数。

MATSim 需要的是个体出行计划，而不是矩阵。因此本项目的核心转换是：

```text
区域 Shapefile + OD 矩阵 F_ij
        ↓
按 OD 流量采样 agent
        ↓
为每个 agent 抽样 home/work 坐标
        ↓
映射到 MATSim network link
        ↓
生成 home → work → home plans.xml.gz
```

## 2. 推荐输入数据

### 必需输入

| 输入 | 格式 | 作用 |
| --- | --- | --- |
| 城市区域划分 | Shapefile / GeoPackage | 每个区域一个固定 `region_id`，几何为 Polygon/MultiPolygon |
| 通勤 OD 矩阵 | `.npy` 或 CSV edge list | `F_ij`，表示从居住区 `i` 到工作区 `j` 的通勤人数 |
| MATSim network | `network.xml` / `network.xml.gz` | 用于把 home/work 坐标映射到可通行 link |
| 坐标系定义 | EPSG / proj string | 保证区域、网络、设施在同一投影坐标系 |

### 推荐输入

| 输入 | 格式 | 作用 |
| --- | --- | --- |
| 人口栅格或居住建筑 | raster / vector | 区域内抽样 home 点时加权 |
| 工作地 POI / 就业强度 | vector / CSV | 区域内抽样 work 点时加权 |
| 年龄/性别结构 | CSV / raster aggregate | 生成 person attributes |
| 出行方式参数 | YAML / JSON | 按距离或群体分配 car/walk/bike/PT |

## 3. 输出到 MATSim 的文件

### 核心输出

`plans.xml.gz`

每个 agent 建议生成一个初始计划：

```xml
<person id="p_000001">
  <attributes>
    <attribute name="subpopulation" class="java.lang.String">default</attribute>
    <attribute name="home_zone" class="java.lang.String">12</attribute>
    <attribute name="work_zone" class="java.lang.String">37</attribute>
  </attributes>
  <plan selected="yes">
    <activity type="h" x="..." y="..." end_time="07:42:00" />
    <leg mode="car" />
    <activity type="w" x="..." y="..." end_time="17:31:00" />
    <leg mode="car" />
    <activity type="h" x="..." y="..." />
  </plan>
</person>
```

当前 `matsim-example-project` 的 scoring config 已经使用 `h` 和 `w`，因此第一版保持 `h/w` 活动类型最省事。

### 推荐辅助输出

| 文件 | 作用 |
| --- | --- |
| `facilities.xml.gz` | 把 home/work 点或区域代表点写成 MATSim facilities |
| `agent_od_debug.csv` | 每个 agent 的 `person_id, home_zone, work_zone, mode, dep_time, home_x, home_y, work_x, work_y` |
| `od_scaled.csv` | 缩放和整数化后的 OD 流量，用于校验 |
| `zones.gpkg` | 统一投影后的区域文件，保留 `region_id` |
| `config-generated.xml` | 指向新 network/plans/facilities 的 MATSim config |

## 4. 生成流程

### Step 1：统一区域索引与坐标系

1. 读取区域 Shapefile/GeoPackage。
2. 确保存在稳定的 `region_id`。
3. 将区域投影到 MATSim network 的坐标系。
4. 计算区域中心点、面积、边界 bbox。
5. 校验 OD 矩阵维度与区域数量一致。

规则：

- OD 矩阵第 `[i, j]` 项必须能映射到区域 `i` 和区域 `j`。
- 论文数据中的对角线值表示 intra-zone flow 未估计，不能简单解释为真实的 0。进入 MATSim 前应单独处理。

### Step 2：处理 OD 矩阵

输入矩阵 `F_ij` 是连续或整数流量。生成 agent 前先做缩放：

```text
scaled_F_ij = F_ij × sample_size
```

整数化建议使用“保总量随机舍入”：

1. `base_ij = floor(scaled_F_ij)`
2. `residual_ij = scaled_F_ij - base_ij`
3. 按 residual 的概率补 0/1，或按全局 residual 权重抽样补足总人数。

这样比直接四舍五入更能保持 OD 分布。

### Step 3：处理 intra-zone flow

论文的 `.npy` 对角线是格式占位，不应默认当作零需求。推荐三种策略：

| 策略 | 适用情况 |
| --- | --- |
| 保守版：不生成对角线通勤 | 只关注跨区 commuting corridor |
| 人口比例补齐 | 有区域居住人口，但缺少真实 intra-zone 数据 |
| 距离衰减估计 | 需要完整出行需求，且有就业/POI 强度 |

第一版建议：

```text
intra_i = min(home_workers_i, work_attractiveness_i) × intra_zone_rate
```

其中 `intra_zone_rate` 可从同类城市标定；没有标定数据时先设为 0.05–0.20 做敏感性分析。

### Step 4：从 OD flow 展开 agent

对每个 OD pair `(i, j)`：

```text
生成 n_ij 个 person
person.home_zone = i
person.work_zone = j
```

`person_id` 推荐：

```text
commuter_{home_zone}_{work_zone}_{sequence}
```

如果 `sample_size < 1`，可以给 person attributes 加：

```text
sample_weight = 1 / sample_size
```

MATSim 本身通常直接跑采样人口，分析时再按 sample weight 扩样。

### Step 5：抽样 home/work 坐标

home 坐标优先级：

1. 居住建筑 footprint 或住址点；
2. 人口栅格加权随机点；
3. 区域 polygon 内均匀随机点；
4. 区域 centroid fallback。

work 坐标优先级：

1. employment / workplace 数据；
2. 工作相关 POI 加权点，例如 office、industrial、commercial、education、healthcare；
3. 区域内 POI 加权随机点；
4. 区域 polygon 内均匀随机点；
5. 区域 centroid fallback。

要避免点落在水域、公园深处或 network 太远处。可设置最大 snap 距离，例如 500–1000 m，超过则重采样或使用最近可达区域中心。

### Step 6：映射到 MATSim network link

MATSim plan 可以只写 `x/y`，但建议同时写 `link` 或至少保证坐标能被 router 找到。

推荐流程：

1. 读取 `network.xml`。
2. 只保留允许目标 mode 的 link，例如 `car`。
3. 为每个 home/work 点找最近 link。
4. 若最近 link 超过阈值，重新抽样。
5. 输出 `home_link_id` 和 `work_link_id` 到 debug CSV。

### Step 7：分配时间

第一版通勤日程：

| 项目 | 推荐分布 |
| --- | --- |
| 上班出发 | 07:00–09:30，正态/三角分布，峰值 08:00 左右 |
| 工作时长 | 7.5–9.0 小时，均值 8 小时 |
| 下班出发 | 上班到达后加工作时长，或直接 16:30–19:00 |
| 随机扰动 | 每个 agent 加 0–30 分钟噪声，避免所有人同时出发 |

当前 equil 示例网络很小，可以先使用：

```text
home end_time = Normal(08:00, 30min)
work end_time = home_end_time + 9h + Normal(0, 20min)
```

### Step 8：分配出行方式

当前项目最小可运行方案：全部设为 `car`。

真实城市建议：

| 距离 | 默认 mode |
| --- | --- |
| 0–1.5 km | walk |
| 1.5–5 km | bike / e-bike |
| 5 km 以上 | car / PT |

如果 network 只有 car，先不要生成 walk/bike/PT，否则 MATSim config 和 network mode 都要一起扩展。

### Step 9：写 MATSim XML

Python 生成器建议输出：

```text
scenarios/<city>/plans.xml.gz
scenarios/<city>/facilities.xml.gz
scenarios/<city>/config-generated.xml
scenarios/<city>/debug/agent_od_debug.csv
scenarios/<city>/debug/od_scaled.csv
```

XML 写入时注意：

- 活动类型必须和 config scoring 中的 activityParams 一致。
- 如果设置了 `subpopulation=default`，config 的 replanning strategy 也必须包含同名 subpopulation。
- 初始 plans 不写 route，让 MATSim 在第一轮 routing/replanning 中生成路线。

## 5. 与当前项目的集成建议

当前项目根目录：

`F:\Matsim\matsim-example-project`

默认 Python 环境：

`F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe`

建议新增生成器：

```text
src/main/python/generate_matsim_agents_from_od.py
```

推荐命令形态：

```powershell
.\.venv_geo311\Scripts\python.exe .\src\main\python\generate_matsim_agents_from_od.py `
  --zones path\to\zones.gpkg `
  --od path\to\od.npy `
  --network scenarios\city\network.xml.gz `
  --output scenarios\city\plans.xml.gz `
  --sample-size 0.1 `
  --mode car `
  --crs EPSG:32650
```

如果直接使用论文/WorldCommuting-OD 已发布的 OD 数据，则不需要本地运行 WEDAN，只需要执行“矩阵转 agent plans”。

如果以后要在本机重新运行 WEDAN 模型，需要额外准备：

- PyTorch 环境；
- WEDAN 模型代码；
- 训练好的权重；
- 区域特征矩阵 `X_R`；
- 区域间距离矩阵 `D_ij`。

当前迁移过来的 `.venv_geo311` 没有 `torch`，因此它适合做 GIS、PDF、OD 后处理和 MATSim XML 生成，不适合直接训练/推理 WEDAN。

## 6. 校验指标

生成 MATSim input 前：

- 区域数量是否等于 OD 矩阵维度。
- 缩放后总 agent 数是否约等于 `sum(F_ij) × sample_size`。
- 每个区域 outflow/inflow 是否与 OD 矩阵一致。
- home/work 坐标是否全部落在区域内。
- home/work 坐标到最近 network link 的距离是否合理。

MATSim 跑完后：

- `output_plans.xml.zst` 中 agent 数是否一致。
- `output_events.xml.zst` 是否有 stuck agents。
- SimWrapper 中 Trips、Traffic、Stuck Agents 是否正常。
- 通勤距离分布是否接近 OD 区域中心距离分布。
- 若有 counts 或手机信令/调查数据，对比 link volume 或 OD corridor。

## 7. 第一版实现范围

第一版建议先做“可运行、可验证”的最小闭环：

1. 读取区域文件和 OD 矩阵。
2. 生成 car-only home-work-home agents。
3. 输出 MATSim `plans.xml.gz`。
4. 生成 debug CSV。
5. 跑 MATSim + SimWrapper 检查 OD、trip、traffic 和 stuck agents。

第二版再加入：

- intra-zone flow 补齐；
- POI/人口栅格加权坐标；
- 多方式 mode choice；
- facilities；
- 年龄、性别、职业等 person attributes；
- 与真实 counts 或外部 OD 的校准。
