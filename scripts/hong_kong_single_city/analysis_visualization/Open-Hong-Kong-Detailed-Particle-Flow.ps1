[CmdletBinding()]
param(
    [string]$VisualizationDirectory = "F:\Matsim\matsim-example-project\runs\hongkong\outputs\formal_50it_ptfixed_ferry_activity_simwrapper\particle-flow-detailed-road-corrected",
    [int]$Port = 8765,
    [switch]$SkipOpen
)

$ErrorActionPreference = "Stop"
$directory = (Resolve-Path -LiteralPath $VisualizationDirectory).Path
$required = @("index.html", "particle_data.js", "particle_flow_summary.json")
$missing = @(
    $required |
        Where-Object {
            -not (Test-Path -LiteralPath (Join-Path $directory $_) -PathType Leaf)
        }
)
if ($missing.Count -gt 0) {
    throw "Particle-flow project is incomplete: $($missing -join ', ')"
}

$index = Join-Path $directory "index.html"
Write-Host "Hong Kong detailed particle flow is ready:"
Write-Host "  $index"
if (-not $SkipOpen) {
    $python = (Get-Command python -ErrorAction Stop).Source
    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        $Port
    )
    try {
        $listener.Start()
    }
    catch {
        throw "Port $Port is already in use. Pass a different -Port value."
    }
    finally {
        $listener.Stop()
    }
    Start-Process -FilePath $python `
        -ArgumentList @(
            "-m", "http.server", "$Port",
            "--bind", "127.0.0.1",
            "--directory", $directory
        ) `
        -WindowStyle Hidden
    Start-Sleep -Seconds 1
    Start-Process "http://127.0.0.1:$Port/index.html"
}
