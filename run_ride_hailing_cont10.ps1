$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "F:\Matsim\matsim-example-project"
New-Item -ItemType Directory -Force -Path ".\run_logs" | Out-Null

$stdout = ".\run_logs\ride_hailing_cont10_current.out.log"
$stderr = ".\run_logs\ride_hailing_cont10_current.err.log"
$mvn = "E:\Program Files\apache-maven-3.9.16\bin\mvn.cmd"

& $mvn `
  exec:java `
  "-Dexec.mainClass=org.matsim.project.RunMatsimModelImplementation" `
  "-Dexec.args=run --config .\scenarios\fuzhou\config-transit-mode-choice-2pct-ride-hailing-cont10.xml" `
  > $stdout 2> $stderr
