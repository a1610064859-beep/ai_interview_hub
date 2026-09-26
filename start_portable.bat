@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\portable\start.ps1"
if errorlevel 1 (
  echo Startup failed. Keep this window open and check logs\portable-*.err.txt.
  pause
  exit /b 1
)
pause
