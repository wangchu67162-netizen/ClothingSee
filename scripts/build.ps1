<#
衣见 ATELIER 构建脚本（Windows PowerShell 5.1+ / PowerShell 7）

执行内容：
  1. 后端导入检查（backend\.venv 中 import app.main，不启动服务器）
  2. 前端生产构建（tsc --noEmit && vite build，输出 frontend\dist）
  3. 校验 frontend\dist\index.html 已生成

用法：
  powershell -ExecutionPolicy Bypass -File scripts\build.ps1
  powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -SkipBackend
  powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -SkipFrontend

构建完成后可运行 scripts\dev.ps1 开发联调；生产演示时后端会自动托管 frontend\dist。
#>
[CmdletBinding()]
param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"

try {
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [Console]::OutputEncoding = $utf8
}
catch {
    # 控制台不支持 UTF-8 时保持默认编码。
}

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPy = Join-Path $Backend ".venv\Scripts\python.exe"

function Write-Step([string]$Message) { Write-Host "== $Message ==" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "[ ok  ] $Message" -ForegroundColor Green }

if ($SkipBackend -and $SkipFrontend) {
    Write-Host "未指定任何构建目标（-SkipBackend 与 -SkipFrontend 同时存在）。"
    exit 0
}

if (-not $SkipBackend) {
    Write-Step "后端导入检查"
    if (-not (Test-Path $VenvPy)) {
        Write-Host "[fail] 未找到 backend\.venv，请先运行 scripts\setup.ps1。" -ForegroundColor Red
        exit 1
    }
    Push-Location $Backend
    try {
        & $VenvPy -c "from app.main import app; print('backend import ok, routes=%d' % len(app.routes))"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[fail] 后端导入检查失败。" -ForegroundColor Red
            exit 1
        }
    }
    finally {
        Pop-Location
    }
    Write-Ok "后端可正常导入（未启动服务器）"
}

if (-not $SkipFrontend) {
    Write-Step "前端生产构建（tsc --noEmit && vite build）"
    $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npmCmd) { $npmCmd = Get-Command npm -ErrorAction SilentlyContinue }
    if (-not $npmCmd) {
        Write-Host "[fail] 未找到 npm，请安装 Node.js 18+。" -ForegroundColor Red
        exit 1
    }
    Push-Location $Frontend
    try {
        & $npmCmd.Source run build
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[fail] 前端构建失败（tsc / vite）。" -ForegroundColor Red
            exit 1
        }
    }
    finally {
        Pop-Location
    }
    $distIndex = Join-Path $Frontend "dist\index.html"
    if (-not (Test-Path $distIndex)) {
        Write-Host "[fail] 未生成 frontend\dist\index.html。" -ForegroundColor Red
        exit 1
    }
    $distAssets = Join-Path $Frontend "dist\assets"
    $assetCount = 0
    if (Test-Path $distAssets) {
        $assetCount = @(Get-ChildItem -Path $distAssets -File).Count
    }
    Write-Ok "前端构建完成：frontend\dist（assets 文件 $assetCount 个）"
}

Write-Host ""
Write-Host "构建完成。生产式演示：先构建，再启动后端（后端会自动托管 frontend\dist）。" -ForegroundColor Green
Write-Host "  后端启动：powershell -ExecutionPolicy Bypass -File scripts\dev.ps1（开发）"
Write-Host "  或：cd backend; .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
