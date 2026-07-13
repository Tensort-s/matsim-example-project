# Project Python Environment

This project uses the migrated Python environment from:

`F:\GreenspaceExposureMeasurement\.venv_geo311`

The default Python interpreter for project-side data processing is:

`F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe`

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
