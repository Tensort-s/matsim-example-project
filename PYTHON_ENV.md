# Project Python Environment

This project uses the migrated Python environment from:

`F:\GreenspaceExposureMeasurement\.venv_geo311`

The default Python interpreter for project-side data processing is:

`F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe`

## Which Python environment should I use?

| Task | Use |
|---|---|
| GIS processing, GeoJSON/Shapefile, OSM, GEE, AMap, raster handling, population feature tables | `.venv_geo311` |
| MATSim agents/routes generation, transit supply preprocessing, CSV/GeoJSON QA, SimWrapper/Kepler post-processing | `.venv_geo311` |
| PDF text extraction and literature-support processing | `.venv_geo311` |
| WEDAN / WorldCommuting-OD inference | `.venv_wedan` |
| RemoteCLIP image feature extraction | `.venv_wedan` |
| Java MATSim simulation and Maven build | Java/Maven, not Python |

Default rule: use `.venv_geo311` for project data processing. Switch to `.venv_wedan` only when the script needs
PyTorch, DGL, WEDAN, or RemoteCLIP.

## Activate in PowerShell

From the project root:

```powershell
cd F:\Matsim\matsim-example-project
.\.venv_geo311\Scripts\Activate.ps1
```

Or run commands without activating:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe your_script.py
```

## Main available packages

This environment includes the packages needed for the MATSim OD-agent workflow and PDF reading, including:

- PyMuPDF / `fitz`
- pandas
- GeoPandas
- Shapely
- Pillow

For IDEs such as VS Code or PyCharm, select the interpreter above as the project interpreter.

## PDF extraction convention

PDF text extracted for literature review or OD-agent design should be written under:

`F:\Matsim\matsim-example-project\docs\pdf-text\`

The extracted text files are ignored by Git because they are derived artifacts.
