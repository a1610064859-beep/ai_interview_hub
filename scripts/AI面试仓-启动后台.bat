@echo off
setlocal
set "LAUNCHER=%~dp0start_local.ps1"
if not exist "%LAUNCHER%" set "LAUNCHER=E:\ai_interview_hub\scripts\start_local.ps1"
if not exist "%LAUNCHER%" (
  echo [ERROR] Launcher not found: "%LAUNCHER%"
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo [ERROR] Startup failed. Read the error above.
) else (
  echo Backend and frontend are running. Closing this window will not stop them.
)
pause
exit /b %EXIT_CODE%
