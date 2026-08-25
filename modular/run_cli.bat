@echo off
title Translator CLI
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found.
  echo Please install Python and make sure "python" is in PATH, then retry.
  pause
  exit /b 1
)

if "%~1"=="" (
  echo Usage: run_cli.bat {baidu^|siliconflow^|lmstudio} [options...]
  echo Example: run_cli.bat lmstudio --input test.json --list-models
  python run_cli.py --help
  pause
  exit /b 0
)

python run_cli.py %*
if errorlevel 1 pause