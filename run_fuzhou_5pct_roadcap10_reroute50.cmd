@echo off
cd /d F:\Matsim\matsim-example-project
if not exist run_logs mkdir run_logs
set RUN_STAMP=%DATE:~0,4%%DATE:~5,2%%DATE:~8,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%
set RUN_STAMP=%RUN_STAMP: =0%
set RUN_STDOUT=run_logs\fuzhou_5pct_roadcap10_reroute50_%RUN_STAMP%.out.log
set RUN_STDERR=run_logs\fuzhou_5pct_roadcap10_reroute50_%RUN_STAMP%.err.log
"E:\Program Files\apache-maven-3.9.16\bin\mvn.cmd" exec:java "-Dexec.mainClass=org.matsim.project.RunMatsimModelImplementation" "-Dexec.args=run --config .\scenarios\fuzhou\config-transit-mode-choice-5pct-reroute-50.xml" > "%RUN_STDOUT%" 2> "%RUN_STDERR%"
set RUN_EXIT=%ERRORLEVEL%
echo ExitCode=%RUN_EXIT% > run_logs\fuzhou_5pct_roadcap10_reroute50_%RUN_STAMP%.exit.txt
exit /b %RUN_EXIT%
