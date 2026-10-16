@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Chưa cài đặt. Bấm đúp CAI_DAT.bat trước.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m backend.main
