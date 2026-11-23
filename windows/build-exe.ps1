# 打包 Windows 11 单文件 exe（在仓库根目录执行）
# 用法：powershell -ExecutionPolicy Bypass -File windows\build-exe.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "[1/4] 检查 Python ..."
$py = "py"; $pyArgs = @("-3")
try { & $py -3 --version | Out-Null } catch { $py = "python"; $pyArgs = @() }

Write-Host "[2/4] 安装依赖 ..."
& $py @pyArgs -m pip install --upgrade pip
& $py @pyArgs -m pip install --upgrade pyinstaller pillow

Write-Host "[3/4] 打包学生端 ..."
& $py @pyArgs -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name ThyClass-Student --paths . run_student.py

Write-Host "[4/4] 打包老师端 ..."
& $py @pyArgs -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name ThyClass-Teacher --paths . run_teacher.py

Write-Host ""
Write-Host "完成：dist\ThyClass-Student.exe、dist\ThyClass-Teacher.exe"
Write-Host "提示：首次运行请允许 Windows 防火墙的“专用网络”访问。"
