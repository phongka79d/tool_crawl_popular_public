@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Đang cài Video Công Thức. Lần đầu mất khoảng 5-15 phút tuỳ mạng (tải ~1 GB). Đừng tắt cửa sổ này.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\cai_dat.ps1"
if errorlevel 1 (
  echo.
  echo Cài đặt chưa xong. Xem dòng LỖI phía trên, sửa rồi bấm lại CAI_DAT.bat - phần đã xong sẽ được giữ.
  pause
  exit /b 1
)
timeout /t 5 >nul
