<#
衣见 ATELIER 开发启动脚本（Windows PowerShell 5.1+ / PowerShell 7）

一条命令同时启动：
  后端 FastAPI  http://127.0.0.1:8000（uvicorn --reload）
  前端 Vite     http://127.0.0.1:5173（代理 /api /static /screenshots /uploads /demo-mall）

用法：
  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1

按 Ctrl+C 会同时停止前后端，不会留下后台服务器。
#>
[CmdletBinding()]
param()

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
$EnvFile = Join-Path $Backend ".env"
$EnvExample = Join-Path $Backend ".env.example"

function Write-Info([string]$Message) { Write-Host "[dev] $Message" -ForegroundColor Cyan }
function Write-Warn([string]$Message) { Write-Host "[warn] $Message" -ForegroundColor Yellow }
function Write-Fail([string]$Message) { Write-Host "[fail] $Message" -ForegroundColor Red }

function Test-PortInUse([int]$Port) {
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return [bool]$listeners
    }
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(300)) { return $false }
        $client.EndConnect($async)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Stop-ProcessTree([int]$ProcessId) {
    if ($ProcessId -le 0) { return }
    try {
        & taskkill.exe /PID $ProcessId /T /F *> $null
    }
    catch {
        # 进程已退出时忽略。
    }
}

if (-not (Test-Path $VenvPy)) {
    Write-Fail "未找到 backend\.venv，请先运行 powershell -ExecutionPolicy Bypass -File scripts\setup.ps1"
    exit 1
}
if (-not (Test-Path (Join-Path $Backend "app\main.py"))) {
    Write-Fail "未找到 backend\app\main.py，请检查项目结构。"
    exit 1
}
if (-not (Test-Path (Join-Path $Frontend "node_modules\vite\package.json"))) {
    Write-Fail "前端依赖未安装，请先运行 scripts\setup.ps1。"
    exit 1
}

$npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCmd) { $npmCmd = Get-Command npm -ErrorAction SilentlyContinue }
if (-not $npmCmd) {
    Write-Fail "未找到 npm，请安装 Node.js 18+。"
    exit 1
}

if (-not (Test-Path $EnvFile) -and (Test-Path $EnvExample)) {
    Copy-Item -Path $EnvExample -Destination $EnvFile
    Write-Info "已从 .env.example 生成 backend\.env（默认 Mock 模式）"
}

if (Test-PortInUse 8000) {
    Write-Fail "端口 8000 已被占用。请先停止占用进程（例如上次未退出的 uvicorn）后重试。"
    exit 1
}
if (Test-PortInUse 5173) {
    Write-Fail "端口 5173 已被占用。请先停止占用进程（例如上次未退出的 Vite）后重试。"
    exit 1
}

$backendArgs = @(
    "-m", "uvicorn", "app.main:app",
    "--host", "127.0.0.1", "--port", "8000",
    "--reload", "--reload-dir", "app"
)

Write-Info "启动后端：http://127.0.0.1:8000 （接口文档 /docs）"
$backend = Start-Process -FilePath $VenvPy -ArgumentList $backendArgs -WorkingDirectory $Backend -PassThru -NoNewWindow
Write-Info "启动前端：http://127.0.0.1:5173"
$frontend = Start-Process -FilePath $npmCmd.Source -ArgumentList @("run", "dev") -WorkingDirectory $Frontend -PassThru -NoNewWindow

Write-Host ""
Write-Host "  前端主站   http://127.0.0.1:5173"
Write-Host "  后端 API   http://127.0.0.1:8000/api/meta"
Write-Host "  接口文档   http://127.0.0.1:8000/docs"
Write-Host "  云裳商城   http://127.0.0.1:8000/demo-mall/"
Write-Host "  演示账号   demo / demo123"
Write-Host ""
Write-Host "  按 Ctrl+C 同时停止前后端。"
Write-Host ""

try {
    while ($true) {
        $backend.Refresh()
        $frontend.Refresh()
        if ($backend.HasExited) {
            $backendCode = if ($null -ne $backend.ExitCode) { $backend.ExitCode } else { "未知" }
            Write-Warn "后端已退出（退出码 $backendCode），正在清理前端 …"
            break
        }
        if ($frontend.HasExited) {
            $frontendCode = if ($null -ne $frontend.ExitCode) { $frontend.ExitCode } else { "未知" }
            Write-Warn "前端已退出（退出码 $frontendCode），正在清理后端 …"
            break
        }
        Start-Sleep -Milliseconds 800
    }
}
finally {
    Write-Info "正在停止前端与后端 …"
    Stop-ProcessTree $frontend.Id
    Stop-ProcessTree $backend.Id
    Write-Info "前后端已停止。"
}

exit 1
