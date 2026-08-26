<!-- ppt-master-schema: design-spec/v1 -->
# Hong Kong MATSim Progress Report - Design Spec

## I. Project Information

| Item | Value |
| --- | --- |
| Project Name | Hong Kong MATSim Progress Report |
| Canvas Format | PPT 16:9 widescreen, 1280 × 720 px |
| Page Count | 11 |
| Primary Language | zh-CN |
| Target Audience | 熟悉交通模型、关注方法可靠性和阶段性证据的导师 |
| Communication Intent | 汇报相对原始基线新增的私家车成本、PT 票价、校巴、家庭实体私家车、有限出租车与交通信号控制能力，并用可复核运行证据说明这些升级已经落地 |
| Desired Audience Outcome | 导师能够清楚区分基线与本轮升级，理解每项新增机制解决的问题、运行方式和证据边界 |
| Core Message / Ask / Action | 香港 MATSim 已从活动计划与效用评分驱动的出行模拟，推进为具备港币成本、稀缺实体车辆、信号控制和事件级审计能力的多模式系统 |
| Delivery Context | 导师阶段性汇报，现场讲解 15–20 分钟，之后可独立审阅和归档 |
| Artifact Afterlife | 导师审阅、研究进展留档，并可复用于论文或项目报告的阶段成果部分 |
| Reading Mode | balanced |
| Content Strategy | 严格保留已有图件、数字、限制条件和证据口径；基线只用一页，主体集中展示本轮八组成果，不加入未来展望 |
| Design Style | 科学证据编辑部：严格网格、克制留白、数据新闻式证据层级，图件为页面主角 |
| AI Image Acquisition Path | not applicable; provided assets only |
| Generation Mode | continuous |
| Spec Refinement | disabled |
| Speaker Notes | enabled — Stage-2 confirmed proactive policy for a presenter-led supervisor report |
| Custom Animations | disabled — Stage-2 confirmed proactive policy |
| Narration Audio | disabled — Stage-2 confirmed proactive policy |
| Created Date | 2026-08-25 |

## II. Canvas Specification

| Property | Value |
| --- | --- |
| Format | ppt169 |
| Dimensions | 1280 × 720 px |
| viewBox | `0 0 1280 720` |
| Margins | 64 px left/right; 42 px top/bottom safe area |
| Content Area | x=64–1216, y=42–678 |

## III. Visual Theme

### Theme Style

- **Mode**: custom
- **Mode References**: pyramid, briefing
- **Mode Behavior**: Open with the completed stage conclusion, then move through eight evidence pages in a stable and scannable sequence. Use assertion titles where the executed evidence supports a finding, but retain briefing-style neutrality for the baseline and all caveats; never invent a benchmark, causal claim, calibration result, or production status. Close by consolidating the evidence into three completed capability shifts rather than adding a recommendation or outlook.
- **Visual style**: custom
- **Visual Style References**: swiss-minimal, data-journalism
- **Visual Style Behavior**: Use a strict modular grid, sharp rectilinear zones, thin rules, and large intentional whitespace. Scientific figures form the page spine; concise native titles, evidence strips, captions, and source lines provide a publication-grade reading hierarchy without repeated cards, decorative gradients, or shadows. Typography is precise and predominantly sans-serif, with restrained emphasis and variable density only where the supplied evidence requires it.
- **Theme**: Hong Kong scientific evidence editorial system derived from the supplied figure language
- **Tone**: rigorous, credible, contemporary, visually confident, and careful about model-versus-observation boundaries

### Color Scheme

| Role | HEX | Purpose |
| --- | --- | --- |
| Background | #FFFFFF | Main page field and full-fidelity figure support |
| Secondary background | #EEF1EF | Quiet evidence bands, baseline zones, and summary fields |
| Primary | #2F7895 | Section markers, progress layer, and stable model-system emphasis |
| Accent | #C45139 | Key mechanism, exception, cost, or operational evidence emphasis |
| Secondary accent | #D1A04A | Limited highlight for timing, fare, or signal coordination details |
| Body text | #202629 | Titles, body copy, figure captions, and source lines |

## IV. Typography System

### Font Plan

| Role | Character (Reference) | Primary | English if non-English | Fallback tail |
| --- | --- | --- | --- | --- |
| Title | neo-grotesque sans, bold and grid-aligned | Microsoft YaHei | Arial | DengXian, sans-serif |
| Body | precise humanist sans, compact and highly legible | Microsoft YaHei | Arial | DengXian, sans-serif |

- **Title stack**: Microsoft YaHei, Arial, DengXian, sans-serif
- **Body stack**: Microsoft YaHei, Arial, DengXian, sans-serif

### Font Size Hierarchy

| Purpose | Anchor Size (px) |
| --- | ---: |
| Body | 22 |
| Title | 40 |
| Subtitle | 28 |
| Annotation | 16 |

## V. Layout Principles

### Deck-wide Direction

- **Hierarchy direction**: Read the conclusion title first, then the complete scientific figure, then a concise evidence or boundary line.
- **Composition tendency**: Use one dominant figure field on every results page, usually full-width beneath a narrow title band; vary only between centered evidence, full-width ultra-wide evidence, and a slightly narrower figure with an adjacent takeaway strip when the source aspect ratio requires it.
- **Cross-page continuity**: Keep page number, section marker, title baseline, figure caption position, source boundary, and the primary/accent color roles stable; allow each supplied figure's own internal composition to remain visually distinct.
- **Spacing posture**: Open around titles and between evidence groups, compact around captions and method notes, with no decorative filler.

## VI. Icon Usage Specification

- **Primary bundled library**: none

| Icon Path | Suitable Scenarios |
| --- | --- |

## VIII. Image Resource List

| Filename | Dimensions | Ratio | Purpose | Type | Layout pattern | Crop Policy | Acquire Via | Status | Reference | text_policy | page_role |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01_hong_kong_model_evolution.png | 3443 × 2206 | 1.56 | Show the complete baseline-to-current model evolution and realised district OD context | Scientific figure | #P1-12 framed evidence figure with complete legend and method note visible | no-crop | user | Existing | Reuse on Slide 03; preserve all labels and full evidence boundary | none | local |
| figure02_school_bus_walk_timing_repair.png | 3277 × 1965 | 1.67 | Explain how continuous link durations repair a real missed school-bus boarding | Scientific figure | #P1-12 full-width evidence figure with a concise native takeaway above | no-crop | user | Existing | Slide 04; retain route map, event timing, accumulated-error panel, and footnote | none | local |
| figure03_household_joint_car_timeline.png | 3701 × 1965 | 1.88 | Demonstrate one household sharing one physical private car through an executed day | Scientific figure | #P1-12 full-width framed timeline with the complete broken-time axis visible | no-crop | user | Existing | Slide 05; preserve household, person, vehicle identifiers and score caveat | none | local |
| 05_hong_kong_finite_taxi_operations.png | 3180 × 2443 | 1.30 | Present finite Taxi fleet operations, flows, utilisation, and empty movement | Scientific figure | #P1-12 centered evidence figure with a narrow metric rail beside it | no-crop | user | Existing | Slide 06; retain radial inset, flow map, ledgers, and method note | none | local |
| figure_04_private_car_cost_anatomy.png | 5034 × 1952 | 2.58 | Decompose one executed private-car trip into energy, toll, and parking HKD components | Scientific figure | #P1-12 ultra-wide figure spanning the evidence field beneath the title | no-crop | user | Existing | Slide 07; preserve every cost component and fixed-ownership exclusion | none | local |
| figure_8_pt_fare_network_central.png | 4325 × 2620 | 1.65 | Show experienced PT fare geography and four exact segment-level itinerary chains | Scientific figure | #P1-12 large framed figure with complete network and itinerary panels | no-crop | user | Existing | Slide 08; preserve strict-key resolution, amount labels, and fare limitations | none | local |
| figure_b_hong_kong_monetary_cost_maps.png | 4504 × 2301 | 1.96 | Compare all-Hong-Kong mean model-rule HKD for total, PT, private car, and Taxi | Scientific figure | #P1-12 full-width geographic small-multiple evidence field | no-crop | user | Existing | Slide 09; preserve all map scales, mode panels, null policy, and universe counts | none | local |
| figure_a_candidate11_signals_greenwave.png | 3828 × 2634 | 1.45 | Show the full signal distribution and a candidate green-wave corridor in map and time-space views | Scientific figure | #P1-12 centered technical evidence figure with complete overview and coordination diagram | no-crop | user | Existing | Slide 10; retain candidate status, corridor offsets, peak bin, and controlled-turn evidence | none | local |

## IX. Content Outline

### Part 1: Framing

#### Slide 01 - Cover

- **Audience move**: From an undefined progress update → to a clear expectation that this report demonstrates a completed shift in model capability.
- **Layout**: Large left-aligned title in an open field; a restrained vertical primary plane and thin district-grid-inspired native linework provide identity without competing with later scientific figures. Branch, commit, date, and report scope form a small lower evidence block.
- **Title**: 香港多模式 MATSim：从出行选择到可审计运行
- **Core message**: 本轮进展把真实金额、实体车辆和交通控制引入了同一个可追溯的香港仿真框架。
- **Content**: Subtitle: “阶段性进展汇报｜成本、实体车辆与信号控制”；three short scope tags: “港币成本”“稀缺实体车辆”“事件级审计”；branch `codex/hk-taxi-dvrp-v1`; commit `593ade88837cb352a7dd61a078e7782f6c041068`; date `2026-08-25`.

#### Slide 02 - Baseline

- **Audience move**: From remembering the earlier model only generally → to seeing exactly what it could express and which questions remained unanswered.
- **Layout**: One-page baseline only. A compact left-to-right native flow shows activity plans → road/PT supply → score-based mode choice; a contrasting lower band lists the four absent capabilities that define this report's comparison boundary.
- **Title**: 基线已经能够模拟出行，但尚不能回答“多少钱、哪辆车、受何种控制”
- **Core message**: 原始版本具备需求、供给和效用选择骨架，但尚未引入私家车成本、PT 票价、校巴和家庭实体私家车机制。
- **Content**: Baseline foundation: synthetic agents and multi-activity plans; road and public-transport supply; score-based mode choice and iterative MATSim execution. Missing at baseline: monetary private-car costs; exact PT fares; school-bus execution; physical household private-car allocation. Report boundary: later slides focus on the newly observable cost, resource, control, and audit evidence; baseline occupies this slide only.

### Part 2: Implemented capability evidence

#### Slide 03 - Model evolution

- **Audience move**: From a list of separate code additions → to one coherent picture of how the model system has evolved.
- **Layout**: Assertion title and one-line standfirst above a large contained scientific figure; a narrow footer identifies iteration-49 sensitivity evidence and the 18-district aggregation.
- **Title**: 模型已从“计划与效用”推进到“成本、实体与控制”
- **Core message**: 新增能力不是孤立模块，而是在原有需求与供给骨架上形成货币、物理资源、信号和审计四个可连接层。
- **Content**: Takeaway line: “742,189 个已实现 iteration-49 trips 提供统一运行背景”；four progress labels: monetary layer, physical-resource layer, signal-control layer, audit layer; boundary: candidate/validation evidence rather than a redefinition of the production run.
- **Images**: Use `01_hong_kong_model_evolution.png` unchanged and fully contained; its map, flow encodings, layer structure, legend, and method note remain the primary evidence.

#### Slide 04 - School-bus timing repair

- **Audience move**: From viewing access walking as a harmless feeder detail → to understanding that seconds of accumulated link rounding can change whether a student boards the vehicle.
- **Layout**: Assertion title and a compact three-time evidence strip above the complete figure; the strip repeats only the decisive event times while the figure carries route and accumulation detail.
- **Title**: 十秒级步行时间误差，决定校巴能否真实登乘
- **Core message**: 将逐链接整数取整改为连续时长后，同一学生从错过车辆恢复为成功登乘，说明校巴机制已经通过事件级机械门槛。
- **Content**: Student `hk_person_00632810`; run56 arrival `07:38:17`; boarding event `07:38:14`; run57 repaired arrival `07:38:07`; accumulated repair `10 s` over `20` walk links. Make clear that the map and timing trace use the real selected trip and actual link sequences.
- **Images**: Use `figure02_school_bus_walk_timing_repair.png` unchanged; preserve both map and lower error-accumulation panel.

#### Slide 05 - Household physical private car

- **Audience move**: From treating car as a freely selectable leg mode → to seeing one named vehicle shared and constrained across a complete household day.
- **Layout**: Wide figure as the page spine beneath the assertion title; a slim side label identifies household, driver, student, and vehicle without recreating the timeline.
- **Title**: 私家车成为家庭共享的稀缺物理资源
- **Core message**: 同一辆车完成送学、继续上班、下午接人和共同返程，家庭计划与车辆可用性开始共同约束出行。
- **Content**: Household `hk_hh_1251667`; driver `hk_person_03051340`; student `hk_person_03051341`; vehicle `hk_vehicle_0210204`; executed sequence: school drop-off → onward drive to work → afternoon pickup → shared return. Caveat: MATSim scores shown are utility, not money and not observed household preferences.
- **Images**: Use `figure03_household_joint_car_timeline.png` unchanged; retain the broken event-time axis, LinkEnter evidence, selected composite plan, Walk baseline, and caveat.

#### Slide 06 - Finite Taxi fleet

- **Audience move**: From understanding Taxi as an abstract mode option → to seeing a finite fleet with requests, vehicle activity, waiting, and empty movement.
- **Layout**: Center the complete standard-landscape figure with a compact right-side metric rail carrying four verified operational quantities; the rail must not obscure the radial inset or map.
- **Title**: 出租车从抽象方式选择变成有限车队运营
- **Core message**: 15,500 辆实体车支撑 186,144 个完成请求，同时暴露仿真终点等待和空驶里程等运营结果。
- **Content**: `15,500` physical vehicles; `186,144` completed requests; `17` waiting requests at simulation horizon; `16.5%` empty-VKT share. Boundary: the monetary Taxi model elsewhere is distance-only and waiting disutility is not converted to HKD.
- **Images**: Use `05_hong_kong_finite_taxi_operations.png` unchanged; preserve district flows, radial request-versus-active-fleet inset, ledgers, and footnote.

#### Slide 07 - Private-car monetary cost

- **Audience move**: From a generic private-car penalty → to an auditable HKD bill tied to route energy, exact-time toll entry, and destination parking.
- **Layout**: Use the ultra-wide figure at maximum contained width beneath a concise title; place the total HKD as a single native pull-stat in the residual title area, not over the figure.
- **Title**: 私家车出行成本可以拆解到具体执行事件
- **Core message**: 一次实际执行的跨区私家车行程形成 HK$122.7，可逐项追溯到能耗、过海隧道收费和目的地停车。
- **Content**: Example `hk_person_01925581`; total `HK$122.7`; route energy `HK$20.7`; Cross-Harbour Tunnel toll at actual LinkEnter time `HK$30.0`; settled destination parking `HK$72.0`. Boundary: fixed ownership remains a vehicle-day sidecar and is not allocated to the trip.
- **Images**: Use `figure_04_private_car_cost_anatomy.png` unchanged; preserve route anatomy, event-time link, three components, and exclusion note.

#### Slide 08 - Experienced PT fare network

- **Audience move**: From assuming PT price can be approximated by distance → to understanding the strict experienced boarding/alighting-chain fare logic and its resolution rate.
- **Layout**: Large contained figure beneath the assertion title; a small evidence line above the image highlights resolution coverage and the strict-key rule without repeating the four itineraries.
- **Title**: PT 票价由实际乘降链严格解析，而非距离近似
- **Core message**: 从 Central–Admiralty 出发的 10,066 条实际行程中，9,792 条获得严格完整票价，且可展开到 MTR、巴士、渡轮和换乘链段。
- **Content**: `10,066` experienced itineraries; `9,792` fully resolved; `97.28%` strict resolution; `42` leading destination stops; four real itinerary examples; ten fare tables/crosswalks verified by SHA256. Boundary: adult-reference/base-Octopus model rules; no individual concession or transfer discount; no distance, reverse-order, full-route, or zero-value fallback.
- **Images**: Use `figure_8_pt_fare_network_central.png` unchanged; preserve network, four itinerary chains, segment amounts, and strict-fare caveat.

#### Slide 09 - Hong Kong monetary cost geography

- **Audience move**: From isolated cost examples → to a territory-wide view of where priced travel is more or less expensive in actual HKD.
- **Layout**: Full-width contained four-map figure with a compact universe-count line above and a null-policy/source line below; the maps remain the clear page focus.
- **Title**: 全港出行成本首次以真实港币呈现空间差异
- **Core message**: 566,437 个已定价行程支持总体、PT、私家车和 Taxi 的固定网格成本表面，并保持未解析记录为 null 而不是零。
- **Content**: Priced universe `566,437`; fully resolved PT `364,160`; complete private-car `16,133`; completed Taxi `186,144`. Cost scope: private car includes energy, exact-time tolls, and settled destination parking; Taxi uses realised occupied distance; exclusions remain visible in the figure note.
- **Images**: Use `figure_b_hong_kong_monetary_cost_maps.png` unchanged; preserve four geographic panels, scales, universe counts, cost scope, and null policy.

#### Slide 10 - Signals and green wave

- **Audience move**: From treating road capacity as spatially static → to seeing explicit signal systems, controlled turns, and a reproducible corridor coordination candidate.
- **Layout**: Center the complete technical figure beneath the assertion title; add a concise five-metric evidence strip in residual space while keeping the Hong Kong overview, local corridor map, and time-space diagram fully visible.
- **Title**: 信号系统已进入全港网络，并可验证绿波协调
- **Core message**: Candidate11 已将全港信号控制编译为 MATSim 系统，并以固定偏移展示一条可复核的晚高峰协调走廊。
- **Content**: `1,445` signal systems; `3,243` groups; `6,941` controlled turns; `14` implemented corridors; `47` distinct corridor systems. Representative `corridor_002` reverse direction offsets: `0, 3, 8, 12 s`; displayed peak bin `20:15–20:30`. Boundary: modeled research candidate, not observed Hong Kong timing.
- **Images**: Use `figure_a_candidate11_signals_greenwave.png` unchanged; preserve global distribution, controlled-turn corridor map, time-space coordination diagram, offsets, and candidate warning.

### Part 3: Synthesis

#### Slide 11 - Completed stage summary

- **Audience move**: From eight detailed pieces of evidence → to three memorable completed shifts that define the current model capability.
- **Layout**: Three large aligned native fields labelled monetary, physical, and auditable; each field carries one sentence and two compact evidence examples. A bottom boundary rule states that these are candidate/validation outcomes and do not silently redefine the adopted production run.
- **Title**: 阶段性升级：货币化、实体化、可审计化
- **Core message**: 本轮工作的核心成果，是把模式选择背后的真实代价、稀缺资源和控制过程转化为可以追踪、检查和解释的运行结果。
- **Content**: Monetary: private-car components, strict PT fares, territory-wide HKD surfaces. Physical: household car, school bus boarding, finite Taxi fleet. Auditable: named agents/vehicles, LinkEnter and boarding events, signal systems and offsets, explicit null/exclusion policies. Closing line: “从‘可以运行’推进到‘可以解释每一次关键运行结果’。” No outlook section.

## X. Speaker Notes Requirements

- **Generation**: enabled
- **Filename**: match each SVG filename under `notes/`
- **Content**: Write concise Chinese presenter notes that open with the page takeaway, explain only the evidence visible on the page, preserve model-versus-observation and candidate-versus-production boundaries, and never add unsupported calibration, causality, or policy claims.
- **Total duration**: 15–20 minutes
- **Notes style**: formal, explanatory, and conversational enough for a supervisor discussion
- **Presentation purpose**: report completed progress and establish methodological reliability
