@echo off
setlocal

set "LAUNCHER=%~dp0scripts\start_local.ps1"
set "RADMIN_LAUNCHER=%~dp0scripts\start_radmin.ps1"
if not exist "%LAUNCHER%" (
  echo [ERROR] Cannot find scripts\start_local.ps1 in this project.
  pause
  exit /b 1
)
if not exist "%RADMIN_LAUNCHER%" (
  echo [ERROR] Cannot find scripts\start_radmin.ps1 in this project.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%"
if errorlevel 1 (
  echo [ERROR] Server startup failed. Check the message above.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%RADMIN_LAUNCHER%"
if errorlevel 1 (
  echo [ERROR] Local server is running, but Radmin port setup failed or was canceled.
  pause
  exit /b 1
)

echo Radmin exposes only the website on TCP 3000; the API remains local on TCP 8000.
echo Local services remain running after this window closes.
exit /b 0
