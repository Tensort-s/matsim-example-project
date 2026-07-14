@echo off
setlocal

set SCRIPT_DIR=%~dp0
pushd "%SCRIPT_DIR%..\..\.." || exit /b 1

if not exist runs\fuzhou\logs mkdir runs\fuzhou\logs
set RUN_STDOUT=runs\fuzhou\logs\waitpenalty_from_cont20_reroute50_latest.out.log
set RUN_STDERR=runs\fuzhou\logs\waitpenalty_from_cont20_reroute50_latest.err.log
set RUN_EXIT_FILE=runs\fuzhou\logs\waitpenalty_from_cont20_reroute50_latest.exit.txt
set MAVEN_CMD=E:\Program Files\apache-maven-3.9.16\bin\mvn.cmd
if not exist "%MAVEN_CMD%" set MAVEN_CMD=%CD%\mvnw.cmd

echo Starting waitpenalty from cont20 reroute50 at %DATE% %TIME% > "%RUN_STDOUT%"
echo Working directory: %CD% >> "%RUN_STDOUT%"
echo Maven: %MAVEN_CMD% >> "%RUN_STDOUT%"

call "%MAVEN_CMD%" exec:java "-Dexec.mainClass=org.matsim.project.RunMatsimModelImplementation" "-Dexec.args=run --config .\scenarios\fuzhou\config-transit-mode-choice-2pct-waitpenalty-metroprefer-from-cont20-reroute50.xml" >> "%RUN_STDOUT%" 2> "%RUN_STDERR%"
set RUN_EXIT=%ERRORLEVEL%
echo ExitCode=%RUN_EXIT% > "%RUN_EXIT_FILE%"
popd
endlocal & exit /b %RUN_EXIT%
