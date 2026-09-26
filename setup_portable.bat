@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\portable\setup.ps1"
if errorlevel 1 (
  echo Setup failed. Keep this window open and send the displayed error to the project owner.
  pause
  exit /b 1
)
pause
