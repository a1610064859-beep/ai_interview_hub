@echo off
setlocal

set "LAUNCHER=%~dp0scripts\start_local.ps1"
if not exist "%LAUNCHER%" (
  echo [ERROR] Cannot find scripts\start_local.ps1 in this project.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%"
if errorlevel 1 (
  echo [ERROR] Server startup failed. Check the message above.
  pause
  exit /b 1
)

echo Backend and frontend are ready. Closing this window will not stop them.
exit /b 0
