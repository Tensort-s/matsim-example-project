[CmdletBinding()]
param(
    [string]$ProjectDirectory = "F:\Matsim\matsim-example-project\runs\hongkong\outputs\formal_50it_v2_simwrapper",
    [switch]$SkipOpen
)

$ErrorActionPreference = "Stop"
$projectPath = (Resolve-Path -LiteralPath $ProjectDirectory).Path

$requiredFiles = @(
    "simwrapper-config.yaml",
    "dashboard-1.yaml",
    "dashboard-2.yaml",
    "dashboard-3.yaml",
    "dashboard-4.yaml",
    "dashboard-5.yaml",
    "dashboard-6.yaml",
    "output_config.xml",
    "output_network.xml.zst",
    "output_transitSchedule.xml.gz",
    "analysis\general\run_info.csv",
    "analysis\population\mode_share.csv",
    "analysis\traffic\traffic_stats_by_link_daily.csv",
    "analysis\pt\pt_pax_volumes.csv.gz"
)

$missingFiles = @(
    $requiredFiles |
        Where-Object { -not (Test-Path -LiteralPath (Join-Path $projectPath $_) -PathType Leaf) }
)
$hourlyTrafficCandidates = @(
    "analysis\traffic\traffic_volume_by_link_hour_car.csv",
    "analysis\traffic\traffic_volume_by_link_hour_car_v2.csv"
)
if (-not ($hourlyTrafficCandidates | Where-Object {
    Test-Path -LiteralPath (Join-Path $projectPath $_) -PathType Leaf
})) {
    $missingFiles += ($hourlyTrafficCandidates -join " or ")
}
if ($missingFiles.Count -gt 0) {
    $details = ($missingFiles | ForEach-Object { "  $_" }) -join [Environment]::NewLine
    throw "Hong Kong SimWrapper project is incomplete:`n$details"
}

Write-Host "Hong Kong SimWrapper project is ready:"
Write-Host "  $projectPath"
Write-Host "Dashboards: Overview, Trips, Traffic, Public Transit, Stuck Agents, Hourly Car Traffic"

if (-not $SkipOpen) {
    Start-Process "https://simwrapper.app"
    Write-Host ""
    Write-Host "In SimWrapper, choose 'Open local folder' and select:"
    Write-Host "  $projectPath"
}
