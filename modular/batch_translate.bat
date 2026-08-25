@echo off
title Batch Translate
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found. Please install Python and add it to PATH.
  pause
  exit /b 1
)

if "%~1"=="" (
  echo Usage: batch_translate.bat {options...}
  echo.
  echo Example:
  echo   batch_translate.bat --input .\articles --base-url https://api.openai.com/v1 --api-key sk-xxx --model gpt-4o --to zh
  echo.
  python batch_translate_files.py --help
  pause
  exit /b 0
)

python batch_translate_files.py %*
if errorlevel 1 pause