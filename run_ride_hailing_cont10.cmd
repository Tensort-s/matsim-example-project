@echo off
cd /d F:\Matsim\matsim-example-project
if not exist run_logs mkdir run_logs
set RUN_STDOUT=run_logs\ride_hailing_cont10_latest.out.log
set RUN_STDERR=run_logs\ride_hailing_cont10_latest.err.log
set RUN_EXIT_FILE=run_logs\ride_hailing_cont10_latest.exit.txt
echo Starting ride_hailing cont10 at %DATE% %TIME% > "%RUN_STDOUT%"
echo Working directory: %CD% >> "%RUN_STDOUT%"
echo Maven: E:\Program Files\apache-maven-3.9.16\bin\mvn.cmd >> "%RUN_STDOUT%"
call "E:\Program Files\apache-maven-3.9.16\bin\mvn.cmd" exec:java "-Dexec.mainClass=org.matsim.project.RunMatsimModelImplementation" "-Dexec.args=run --config .\scenarios\fuzhou\config-transit-mode-choice-2pct-ride-hailing-cont10.xml" >> "%RUN_STDOUT%" 2> "%RUN_STDERR%"
set RUN_EXIT=%ERRORLEVEL%
echo ExitCode=%RUN_EXIT% > "%RUN_EXIT_FILE%"
exit /b %RUN_EXIT%
