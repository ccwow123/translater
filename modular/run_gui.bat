@echo off
cd /d "%~dp0"

rem 智能解析：优先使用 launcher.ini 配置 / 自动探测到带 tkinterdnd2 的 pythonw（保证拖拽可用）；失败则用系统 pythonw 兜底
for /f "usebackq delims=" %%P in (`python "%~dp0_launcher_resolve.py"`) do set "LAUNCH_PYW=%%P"
if defined LAUNCH_PYW (
  start "" "%LAUNCH_PYW%" run_gui.py
  goto :eof
)

where pythonw >nul 2>nul
if errorlevel 1 goto :try_python
start "" pythonw run_gui.py
goto :eof

:try_python
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Please install Python and re-run this file.> launch_error.log
  exit /b 1
)
start "" python run_gui.py
goto :eof