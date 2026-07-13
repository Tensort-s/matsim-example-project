$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvActivate = Join-Path $ProjectRoot ".venv_wedan\Scripts\Activate.ps1"

if (-not (Test-Path -LiteralPath $VenvActivate)) {
    throw "WEDAN virtual environment not found: $VenvActivate"
}

& $VenvActivate
$env:DGLBACKEND = "pytorch"
$env:PYTHONPATH = Join-Path $ProjectRoot "data\worldcommuting_od\GeneratingCodeData\code"

Write-Host "Activated WEDAN inference environment."
Write-Host "Python: $ProjectRoot\.venv_wedan\Scripts\python.exe"
Write-Host "DGLBACKEND=$env:DGLBACKEND"
Write-Host "PYTHONPATH=$env:PYTHONPATH"
