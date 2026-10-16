@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3.11 --version >nul 2>&1
if errorlevel 1 (
  echo Chưa có Python 3.11. Tải tại https://www.python.org/downloads/release/python-3119/ rồi chạy lại file này.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3.11 -m venv .venv || goto loi
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || goto loi
echo.
echo Cài đặt xong. Bấm đúp CHAY_APP.bat để mở ứng dụng.
pause
exit /b 0
:loi
echo.
echo Cài đặt lỗi. Xem thông báo phía trên.
pause
exit /b 1
