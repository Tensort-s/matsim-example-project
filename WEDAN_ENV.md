# WEDAN / WorldCommuting-OD Inference Environment

This project has a separate Python environment for WorldCommuting-OD / WEDAN inference:

`F:\Matsim\matsim-example-project\.venv_wedan\Scripts\python.exe`

It is intentionally separate from `.venv_geo311`, which is used for GIS/PDF/data-processing tasks.

## Activate

From the project root:

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -Command ". .\scripts\Activate-WEDAN.ps1; python --version"
```

For an interactive PowerShell session, dot-source the script so the environment remains active in the current shell:

```powershell
. .\scripts\Activate-WEDAN.ps1
```

If your PowerShell execution policy blocks local scripts, start PowerShell with `-ExecutionPolicy Bypass`, or run commands directly with:

```powershell
$env:DGLBACKEND = "pytorch"
$env:PYTHONPATH = "F:\Matsim\matsim-example-project\data\worldcommuting_od\_shared\GeneratingCodeData\code"
F:\Matsim\matsim-example-project\.venv_wedan\Scripts\python.exe your_script.py
```

The activation script sets:

```powershell
$env:DGLBACKEND = "pytorch"
$env:PYTHONPATH = "F:\Matsim\matsim-example-project\data\worldcommuting_od\_shared\GeneratingCodeData\code"
```

These are required so that DGL uses the PyTorch backend and the downloaded WEDAN source code can be imported.

## Installed core versions

The verified working combination is:

- Python 3.10
- PyTorch `2.3.0+cpu`
- DGL `1.1.2`
- NumPy `1.26.4`
- SciPy `1.15.3`
- scikit-learn `1.7.2`
- GeoPandas `1.1.4`

This is a CPU-only environment. It is slower than GPU inference, but avoids CUDA setup complexity and is sufficient for testing, model loading, and small-city inference workflows.

## Local WorldCommuting-OD files

Downloaded source code and model:

```text
F:\Matsim\matsim-example-project\data\worldcommuting_od\_shared\GeneratingCodeData\
```

Important files:

```text
code\main.py
code\model.py
code\eval.py
code\data_load.py
exp\config\us.json
exp\model\US2world\model_666_best.pkl
```

Downloaded Fuzhou feature data:

```text
F:\Matsim\matsim-example-project\data\worldcommuting_od\fuzhou\330_CN_Fuzhou\
```

The verified Fuzhou input shapes are:

```text
worldpop.npy  (225, 2)
demos.npy     (225, 36)
pois.npy      (225, 34)
imgfeat.npy   (225, 1024)
dis.npy       (225, 225)
```

The WEDAN model was successfully instantiated with:

```text
n_indim = 1096
img_dim = 1024
```

and the checkpoint loaded with:

```text
missing keys = 0
unexpected keys = 0
```

## Quick verification command

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -Command ". .\scripts\Activate-WEDAN.ps1; python -c 'import torch, dgl, numpy; from dgl.dataloading import GraphDataLoader; print(torch.__version__, dgl.__version__, numpy.__version__)'"
```

Expected:

```text
2.3.0+cpu 1.1.2 1.26.4
```
