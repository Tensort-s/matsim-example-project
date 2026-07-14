# Windows 下启动 MATSim 长时间仿真的稳定方式

本项目在 Windows / PowerShell 环境下运行 MATSim 长仿真时，优先使用 `.cmd` 启动脚本，而不是在 PowerShell 里直接拼接复杂的 `Start-Process`、重定向和嵌套引号。

## 已验证成功的模式

参考：

```text
run_fuzhou_5pct_roadcap10_reroute50.cmd
```

该脚本曾成功完成 50 轮仿真，并写入完整 stdout / stderr / exit code。

稳定模板如下：

```bat
@echo off
cd /d F:\Matsim\matsim-example-project
if not exist run_logs mkdir run_logs
set RUN_STAMP=%DATE:~0,4%%DATE:~5,2%%DATE:~8,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6%
set RUN_STAMP=%RUN_STAMP: =0%
set RUN_STDOUT=runs\fuzhou\logs\YOUR_RUN_NAME_%RUN_STAMP%.out.log
set RUN_STDERR=runs\fuzhou\logs\YOUR_RUN_NAME_%RUN_STAMP%.err.log
call "E:\Program Files\apache-maven-3.9.16\bin\mvn.cmd" exec:java "-Dexec.mainClass=org.matsim.project.RunMatsimModelImplementation" "-Dexec.args=run --config .\scenarios\fuzhou\YOUR_CONFIG.xml" > "%RUN_STDOUT%" 2> "%RUN_STDERR%"
set RUN_EXIT=%ERRORLEVEL%
echo ExitCode=%RUN_EXIT% > runs\fuzhou\logs\YOUR_RUN_NAME_%RUN_STAMP%.exit.txt
exit /b %RUN_EXIT%
```

## 为什么这样做

Windows 下 PowerShell + Maven + `-Dexec.args="..."` + stdout/stderr 重定向很容易遇到引号、环境变量大小写、后台进程继承等问题。表现包括：

- 后台进程一闪而过；
- 不生成 MATSim output 目录；
- stdout/stderr 文件为空；
- `Start-Process` 报 `PATH/Path` 字典键冲突；
- 前台命令能跑，但后台命令不能跑。

因此长仿真推荐使用 `.cmd` 文件承载完整命令。注意：在 `.cmd` 中调用另一个 `.cmd`，例如 Maven 的 `mvn.cmd`，建议使用 `call "...\mvn.cmd"`，否则脚本可能不返回到后续的 exit-code 记录逻辑。

## 当前 ride-hailing 10 轮脚本

当前网约车 10 轮正式仿真脚本：

```text
run_ride_hailing_cont10.cmd
```

它已按上述稳定模板修改，使用：

```text
scenarios\fuzhou\config-transit-mode-choice-2pct-ride-hailing-cont10.xml
```

输出目录：

```text
output-fuzhou-transit-mode-choice-2pct-ride-hailing-cont10
```

日志位置：

```text
runs\fuzhou\logs\ride_hailing_cont10_*.out.log
runs\fuzhou\logs\ride_hailing_cont10_*.err.log
runs\fuzhou\logs\ride_hailing_cont10_*.exit.txt
```

## 后续监控

启动后优先查看：

```powershell
Get-ChildItem .\runs\fuzhou\logs\ride_hailing_cont10_* | Sort-Object LastWriteTime -Descending | Select-Object -First 10
```

以及 MATSim 输出日志：

```powershell
Select-String -Path .\output-fuzhou-transit-mode-choice-2pct-ride-hailing-cont10\logfile.log `
  -Pattern "ITERATION|ERROR|Exception|S H U T D O W N" `
  -CaseSensitive:$false |
  Select-Object -Last 80
```

成功完成的关键标志：

```text
### ITERATION 10 ENDS
S H U T D O W N   ---   shutdown completed.
ExitCode=0
```
