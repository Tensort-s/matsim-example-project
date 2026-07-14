[CmdletBinding()]
param(
    [string]$OutputDirectory = "runs/fuzhou/outputs/waitpenalty-metroprefer-from-cont20-reroute50",
    [string]$ScenarioConfig = "scenarios\fuzhou\config-transit-mode-choice-2pct-waitpenalty-metroprefer-from-cont20-reroute50.xml",
    [switch]$SkipOpen
)

$ErrorActionPreference = "Stop"

function Find-ProjectRoot {
    param([string]$StartDirectory)

    $dir = (Resolve-Path -LiteralPath $StartDirectory).Path
    while ($true) {
        $pomPath = Join-Path $dir "pom.xml"
        $fatJarPath = Join-Path $dir "matsim-example-project-0.0.1-SNAPSHOT.jar"
        if ((Test-Path -LiteralPath $pomPath -PathType Leaf) -or (Test-Path -LiteralPath $fatJarPath -PathType Leaf)) {
            return $dir
        }

        $parent = Split-Path -Parent $dir
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $dir) {
            throw "Could not locate project root from script directory: $StartDirectory"
        }
        $dir = $parent
    }
}

$projectRoot = Find-ProjectRoot -StartDirectory $PSScriptRoot
$jarPath = Join-Path $projectRoot "matsim-example-project-0.0.1-SNAPSHOT.jar"
$outputPath = Join-Path $projectRoot $OutputDirectory
$outputConfigPath = Join-Path $outputPath "output_config.xml"
$scenarioConfigPath = Join-Path $projectRoot $ScenarioConfig
$simWrapperConfigPath = Join-Path $outputPath "simwrapper-config.yaml"
$personsPath = Join-Path $outputPath "output_persons.csv.zst"

if (-not (Test-Path -LiteralPath $jarPath -PathType Leaf)) {
    throw "Executable JAR not found: $jarPath`nRun '.\mvnw.cmd clean package -DskipTests' first."
}

if (-not (Test-Path -LiteralPath $outputPath -PathType Container)) {
    throw "MATSim output directory not found: $outputPath"
}

if (-not (Test-Path -LiteralPath $outputConfigPath -PathType Leaf)) {
    throw "MATSim output config not found: $outputConfigPath"
}

if (-not (Test-Path -LiteralPath $scenarioConfigPath -PathType Leaf)) {
    throw "MATSim scenario config not found: $scenarioConfigPath"
}

function Add-DefaultSubpopulationColumn {
    param([string]$CompressedCsvPath)

    if (-not (Test-Path -LiteralPath $CompressedCsvPath -PathType Leaf)) {
        throw "MATSim persons file not found: $CompressedCsvPath"
    }

    $zstd = Get-Command "zstd.exe" -ErrorAction SilentlyContinue
    if (-not $zstd) {
        $zstd = Get-Command "zstd" -ErrorAction SilentlyContinue
    }
    if (-not $zstd) {
        throw "The existing persons file may need a compatibility update, but 'zstd' was not found in PATH."
    }

    $rawPath = [System.IO.Path]::GetTempFileName()
    $patchedPath = [System.IO.Path]::GetTempFileName()

    try {
        & $zstd.Source -d -f $CompressedCsvPath -o $rawPath
        if ($LASTEXITCODE -ne 0) {
            throw "Could not decompress $CompressedCsvPath."
        }

        $reader = [System.IO.StreamReader]::new($rawPath)
        try {
            $header = $reader.ReadLine()
            if ($null -eq $header) {
                throw "Persons CSV is empty: $CompressedCsvPath"
            }

            if (($header -split ";") -contains "subpopulation") {
                return
            }

            Write-Host "Adding the missing 'subpopulation' column required by MATSim 2026 TripAnalysis."
            $writer = [System.IO.StreamWriter]::new($patchedPath, $false, [System.Text.UTF8Encoding]::new($false))
            try {
                $writer.WriteLine("$header;subpopulation")
                while (($line = $reader.ReadLine()) -ne $null) {
                    $writer.WriteLine("$line;default")
                }
            }
            finally {
                $writer.Dispose()
            }
        }
        finally {
            $reader.Dispose()
        }

        $backupPath = Join-Path (Split-Path -Parent $CompressedCsvPath) "persons-before-simwrapper.zst"
        if (-not (Test-Path -LiteralPath $backupPath)) {
            Copy-Item -LiteralPath $CompressedCsvPath -Destination $backupPath
        }

        & $zstd.Source -f $patchedPath -o $CompressedCsvPath
        if ($LASTEXITCODE -ne 0) {
            throw "Could not recompress the compatible persons CSV."
        }
    }
    finally {
        Remove-Item -LiteralPath $rawPath, $patchedPath -Force -ErrorAction SilentlyContinue
    }
}

Add-DefaultSubpopulationColumn -CompressedCsvPath $personsPath

Write-Host "Generating SimWrapper dashboards for:"
Write-Host "  $outputPath"

& java -cp $jarPath org.matsim.simwrapper.SimWrapperRunner "--config=$scenarioConfigPath" $outputPath
if ($LASTEXITCODE -ne 0) {
    throw "SimWrapper generation failed with exit code $LASTEXITCODE."
}

$expectedFiles = @(
    $simWrapperConfigPath,
    (Join-Path $outputPath "analysis\general\run_info.csv"),
    (Join-Path $outputPath "analysis\population\mode_share.csv"),
    (Join-Path $outputPath "analysis\traffic\traffic_stats_by_link_daily.csv"),
    (Join-Path $outputPath "analysis\population\stuck_agents.csv")
)

$optionalCountComparisonPath = Join-Path $outputPath "analysis\traffic\count_comparison_daily.csv"
if (-not (Test-Path -LiteralPath $optionalCountComparisonPath -PathType Leaf)) {
    Write-Host "Traffic count comparison was not generated; this is expected when no count input is configured."
}

$missingFiles = @($expectedFiles | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
$dashboardFiles = @(Get-ChildItem -LiteralPath $outputPath -Filter "dashboard-*.yaml" -File)

if ($missingFiles.Count -gt 0 -or $dashboardFiles.Count -lt 5) {
    $details = ($missingFiles | ForEach-Object { "  $_" }) -join [Environment]::NewLine
    throw "SimWrapper generation was incomplete. Missing expected files:`n$details"
}

Write-Host ""
Write-Host "SimWrapper dashboards generated successfully."
Write-Host "Dashboards generated: $($dashboardFiles.Count)"
Write-Host "Dashboard folder:"
Write-Host "  $outputPath"

if (-not $SkipOpen) {
    Write-Host ""
    Write-Host "Opening https://simwrapper.app"
    Write-Host "In SimWrapper, choose the local folder shown above."
    Start-Process "https://simwrapper.app"
}
