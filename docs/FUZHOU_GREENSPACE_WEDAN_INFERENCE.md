# Greenspace 福州新格网 WEDAN 推理

本项目已使用 Greenspace 福州 `city_id=23` 新格网运行 WEDAN/WorldCommuting-OD 模型推理，生成 `438 × 438` OD 矩阵。

## 输入特征

```text
data/worldcommuting_od/custom_features/fuzhou_city_23_greenspace_grid/GeneratingCodeData/data/global_cities/fuzhou_city_23_greenspace_grid/
```

已使用的文件：

```text
nfeat/worldpop.npy  (438, 2)
nfeat/demos.npy     (438, 36)
nfeat/pois.npy      (438, 34)
nfeat/imgfeat.npy   (438, 1024)
adj/dis.npy         (438, 438)
```

节点特征总维度：

```text
2 + 36 + 34 + 1024 = 1096
```

## 模型

```text
data/worldcommuting_od/GeneratingCodeData/exp/model/US2world/model_666_best.pkl
```

## 运行命令

```powershell
cd F:\Matsim\matsim-example-project
$env:DGLDEFAULTDIR='F:\Matsim\matsim-example-project\.dgl'
.\.venv_wedan\Scripts\python.exe scripts\run_fuzhou_greenspace_wedan_inference.py --sample-times 10 --ddim-steps 25
```

## 输出

```text
data/worldcommuting_od/custom_features/fuzhou_city_23_greenspace_grid/CommutingODFlows/fuzhou_city_23_greenspace_grid/
```

主要文件：

```text
generation.npy
generation.csv
generation.png
generation_raw_normalized.npy
generation_summary.json
```

当前结果：

```text
generation.npy: (438, 438)
sum:            27,912,044
nonzero OD:     190,053
max flow:       917
diagonal sum:   0
```

## 重要说明：尺度校准

当前本地仓库有训练好的 `model_666_best.pkl`，但没有保存训练时的 US 数据 scaler。原始 `main.py` 会通过读取 `data/US/` 训练集重新构造 feature/dis/OD 的 MinMax scaler；这套训练数据当前不在本地。

因此本脚本保存两类输出：

1. `generation_raw_normalized.npy`

   模型直接输出的归一化空间矩阵。

2. `generation.npy`

   使用已下载的 WorldOD 福州参考 OD 分布做 off-diagonal quantile mapping 后得到的参考尺度矩阵。它保留新格网模型输出的 OD 排序结构，但流量数值尺度来自参考福州 OD 分布。

这版结果可以继续用于 MATSim agent 生成、OD 筛选、可视化和 Valhalla 成本约束实验；如果要获得严格复现论文训练尺度的 count 结果，需要补齐原始训练 scaler 或重新训练/校准模型。
