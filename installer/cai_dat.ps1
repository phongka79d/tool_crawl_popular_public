# Cài đặt một lần bấm cho Video Công Thức (bản public). Gọi từ CAI_DAT.bat.
# Chạy lại an toàn: bước nào đã xong thì bỏ qua, chỉ làm tiếp phần còn thiếu.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # thanh tiến trình của Invoke-WebRequest làm tải chậm hẳn
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host ""; Write-Host "LỖI: $text" -ForegroundColor Red; exit 1 }
# Lỗi bất ngờ (không qua Fail) vẫn hiện thành một dòng LỖI dễ đọc.
trap { Write-Host ""; Write-Host "LỖI: $_" -ForegroundColor Red; exit 1 }

if ($Root -match '\\AppData\\Local\\Temp\\' -or $Root -match '\.zip\\') {
    Fail "Bạn đang chạy ngay trong file ZIP. Bấm chuột phải file ZIP -> Extract All (Giải nén tất cả), mở thư mục vừa giải nén rồi bấm lại CAI_DAT.bat."
}

function Find-Python {
    $candidates = @()
    try { $candidates += (& py -3.11 -c "import sys; print(sys.executable)" 2>$null) } catch {}
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    $candidates += "$env:ProgramFiles\Python311\python.exe"
    foreach ($exe in $candidates) {
        if ($exe -and (Test-Path -LiteralPath $exe)) {
            $version = try { & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null } catch { $null }
            if ($version -eq '3.11') { return $exe }
        }
    }
    return $null
}

Step "Kiểm tra Python 3.11"
$Python = Find-Python
if (-not $Python) {
    Write-Host "Chưa có Python 3.11, đang cài tự động (chỉ cho tài khoản này, không cần quyền quản trị)..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        & winget install -e --id Python.Python.3.11 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
        $Python = Find-Python
    }
    if (-not $Python) {
        $setup = Join-Path $env:TEMP 'python-3.11.9-amd64.exe'
        Write-Host "Tải bộ cài Python từ python.org (~25 MB)..."
        Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile $setup
        Start-Process -FilePath $setup -ArgumentList '/quiet', 'InstallAllUsers=0', 'Include_launcher=1', 'PrependPath=1', 'Include_test=0' -Wait
        $Python = Find-Python
    }
    if (-not $Python) { Fail "Không cài được Python 3.11. Kiểm tra mạng rồi chạy lại CAI_DAT.bat." }
}
Write-Host "Python: $Python"

Step "Kiểm tra Microsoft Edge WebView2 (khung hiển thị của ứng dụng)"
$webviewKeys = @(
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
    'HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
    'HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}')
$hasWebView = $false
foreach ($key in $webviewKeys) {
    $pv = (Get-ItemProperty -Path $key -Name pv -ErrorAction SilentlyContinue).pv
    if ($pv -and $pv -ne '0.0.0.0') { $hasWebView = $true }
}
if ($hasWebView) {
    Write-Host "Đã có."
} else {
    Write-Host "Chưa có, đang cài..."
    $setup = Join-Path $env:TEMP 'MicrosoftEdgeWebview2Setup.exe'
    Invoke-WebRequest -UseBasicParsing 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $setup
    Start-Process -FilePath $setup -ArgumentList '/silent', '/install' -Wait
}

Step "Tạo môi trường chạy riêng (.venv)"
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $VenvPython) {
    # .venv chép từ máy khác hoặc Python cũ đã gỡ thì không chạy được: tạo lại.
    $ok = try { & $VenvPython -c "import sys" 2>$null; $LASTEXITCODE -eq 0 } catch { $false }
    if (-not $ok) { Remove-Item -LiteralPath (Join-Path $Root '.venv') -Recurse -Force }
}
if (-not (Test-Path -LiteralPath $VenvPython)) {
    & $Python -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { Fail "Không tạo được .venv." }
}

Step "Cài thư viện (lần đầu vài phút)"
$installed = $false
foreach ($attempt in 1, 2) {
    & $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $Root 'requirements.txt')
    if ($LASTEXITCODE -eq 0) { $installed = $true; break }
    Write-Host "Cài thư viện chưa xong, thử lại..." -ForegroundColor Yellow
}
if (-not $installed) { Fail "Không cài được thư viện. Kiểm tra mạng rồi chạy lại CAI_DAT.bat." }

Step "Tải trước mô hình chép lời và trình duyệt quét"
& $VenvPython -m backend.prepare
if ($LASTEXITCODE -ne 0) { Fail "Tải dữ liệu chưa xong. Kiểm tra mạng rồi chạy lại CAI_DAT.bat (phần đã tải được giữ lại)." }

Step "Tạo lối tắt trên Desktop"
# IShellLinkW thay cho WScript.Shell: WScript không lưu được tên/đường dẫn có dấu tiếng Việt.
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;
[ComImport, Guid("00021401-0000-0000-C000-000000000046")] class CShellLink {}
[ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
interface IShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder file, int size, IntPtr data, int flags);
    void GetIDList(out IntPtr list);
    void SetIDList(IntPtr list);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder name, int size);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string name);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder dir, int size);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string dir);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder args, int size);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string args);
    void GetHotkey(out short key);
    void SetHotkey(short key);
    void GetShowCmd(out int show);
    void SetShowCmd(int show);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int size, out int index);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, int reserved);
    void Resolve(IntPtr window, int flags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string file);
}
public static class VctShortcut {
    public static void Create(string lnk, string target, string dir, string icon, int index) {
        var link = (IShellLinkW)new CShellLink();
        link.SetPath(target);
        link.SetWorkingDirectory(dir);
        link.SetIconLocation(icon, index);
        link.SetShowCmd(7);   // thu nhỏ cửa sổ đen của file .bat
        ((IPersistFile)link).Save(lnk, false);
    }
}
"@
$desktop = [Environment]::GetFolderPath('Desktop')
[VctShortcut]::Create((Join-Path $desktop 'Video Công Thức.lnk'), (Join-Path $Root 'CHAY_APP.bat'), $Root,
    (Join-Path $Root 'frontend\img\logo.ico'), 0)
Write-Host "Đã tạo 'Video Công Thức' trên Desktop."

Write-Host ""
Write-Host "CÀI ĐẶT XONG. Đang mở ứng dụng..." -ForegroundColor Green
Start-Process -FilePath (Join-Path $Root 'CHAY_APP.bat') -WorkingDirectory $Root -WindowStyle Minimized
exit 0
