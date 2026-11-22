<#
衣见 ATELIER 一键环境准备（Windows PowerShell 5.1+ / PowerShell 7）

用法：
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Check
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Refresh
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -WithBrowser

  -Check         只检查环境，不做任何安装/写文件
  -SkipInstall   不执行 pip/npm 安装（依赖已就绪时使用）
  -Refresh       强制重新安装前端依赖
  -WithBrowser   额外安装 Playwright Chromium（可选）

本脚本不会启动任何服务器。
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$SkipInstall,
    [switch]$Refresh,
    [switch]$WithBrowser
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
$ReqFile = Join-Path $Backend "requirements.txt"
$EnvFile = Join-Path $Backend ".env"
$EnvExample = Join-Path $Backend ".env.example"
$VenvPy = Join-Path $Backend ".venv\Scripts\python.exe"

function Write-Info([string]$Message) { Write-Host "[setup] $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "[ ok  ] $Message" -ForegroundColor Green }
function Write-Warn([string]$Message) { Write-Host "[warn ] $Message" -ForegroundColor Yellow }
function Write-Fail([string]$Message) { Write-Host "[fail ] $Message" -ForegroundColor Red }

if (-not (Test-Path $Backend) -or -not (Test-Path $Frontend)) {
    Write-Fail "项目结构不完整：未找到 backend\ 或 frontend\（当前根目录：$Root）"
    exit 1
}

$Ready = $true

# ------------------------------------------------------------------ Python / venv
if (-not (Test-Path $VenvPy)) {
    if ($Check) {
        Write-Warn "未找到 backend\.venv（运行 scripts\setup.ps1 创建）"
        $Ready = $false
    }
    else {
        $systemPython = $null
        $pyCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($pyCmd) { $systemPython = $pyCmd.Source }
        if (-not $systemPython) {
            $pyCmd = Get-Command python3 -ErrorAction SilentlyContinue
            if ($pyCmd) { $systemPython = $pyCmd.Source }
        }
        if (-not $systemPython) {
            $launcher = Get-Command py -ErrorAction SilentlyContinue
            if ($launcher) { $systemPython = $launcher.Source }
        }
        if (-not $systemPython) {
            Write-Fail "未找到 Python。请安装 Python 3.10+ 后重试。"
            exit 1
        }
        Write-Info "创建虚拟环境 backend\.venv …"
        if ((Split-Path -Leaf $systemPython) -ieq "py.exe") {
            & $systemPython -3 -m venv (Join-Path $Backend ".venv")
        }
        else {
            & $systemPython -m venv (Join-Path $Backend ".venv")
        }
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPy)) {
            Write-Fail "虚拟环境创建失败，请检查 Python 安装。"
            exit 1
        }
    }
}

if (Test-Path $VenvPy) {
    & $VenvPy -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Python 版本过低（需要 3.10+）：$(& $VenvPy --version 2>&1)"
        $Ready = $false
    }
    else {
        $pyVersion = (& $VenvPy -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
        Write-Ok "Python $pyVersion"
    }

    $hash = ""
    if (Test-Path $ReqFile) {
        $hash = (Get-FileHash -Path $ReqFile -Algorithm SHA256).Hash.ToLower()
    }
    $marker = Join-Path $Backend ".venv\.yijian-requirements.sha256"
    $markerHash = ""
    if (Test-Path $marker) {
        $markerHash = (Get-Content -Path $marker -Raw).Trim()
    }

    $importsOk = $false
    & $VenvPy -c "import fastapi, uvicorn, sqlalchemy, pydantic, jwt, httpx, PIL, numpy, multipart, pytest" *> $null
    if ($LASTEXITCODE -eq 0) { $importsOk = $true }

    $needInstall = $false
    if (-not $importsOk) {
        $needInstall = $true
    }
    elseif ($markerHash -ne "" -and $markerHash -ne $hash) {
        $needInstall = $true
    }

    if ($Check) {
        if ($needInstall) {
            Write-Warn "后端依赖不满足 requirements.txt（运行 scripts\setup.ps1 安装）"
            $Ready = $false
        }
        else {
            Write-Ok "后端依赖已安装"
        }
    }
    elseif (-not $needInstall) {
        if (-not (Test-Path $marker) -and $hash -ne "") {
            Set-Content -Path $marker -Value $hash -NoNewline -Encoding ascii
        }
        Write-Ok "后端依赖已就绪"
    }
    elseif ($SkipInstall) {
        Write-Warn "后端依赖缺失，但指定了 -SkipInstall"
        $Ready = $false
    }
    else {
        Write-Info "安装后端依赖（pip -r requirements.txt）…"
        & $VenvPy -m pip install --disable-pip-version-check -r $ReqFile
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "后端依赖安装失败（pip 退出码 $LASTEXITCODE）。"
            exit 1
        }
        if ($hash -ne "") {
            Set-Content -Path $marker -Value $hash -NoNewline -Encoding ascii
        }
        Write-Ok "后端依赖安装完成"
    }
}

# ------------------------------------------------------------------ .env
if (Test-Path $EnvFile) {
    Write-Ok "backend\.env 已存在"
}
elseif ($Check) {
    Write-Warn "缺少 backend\.env（运行 scripts\setup.ps1 自动生成）"
    $Ready = $false
}
elseif (Test-Path $EnvExample) {
    Copy-Item -Path $EnvExample -Destination $EnvFile
    Write-Ok "已从 .env.example 生成 backend\.env（默认 Mock 模式，无需 API Key）"
}
else {
    Write-Warn "缺少 backend\.env.example，无法生成 .env"
    $Ready = $false
}

# ------------------------------------------------------------------ Node / npm
$nodeOk = $false
if (Get-Command node -ErrorAction SilentlyContinue) {
    $nodeVersion = (& node -v).Trim()
    $nodeMajor = [int]((& node -p "process.versions.node.split('.')[0]").Trim())
    if ($nodeMajor -ge 18) {
        Write-Ok "Node.js $nodeVersion"
        $nodeOk = $true
    }
    else {
        Write-Warn "Node.js 版本过低（需要 18+）：$nodeVersion"
        $Ready = $false
    }
}
else {
    Write-Warn "未找到 Node.js（需要 18+，推荐 Node 24）"
    $Ready = $false
}

$npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCmd) { $npmCmd = Get-Command npm -ErrorAction SilentlyContinue }
if ($npmCmd) {
    $npmVersion = (& $npmCmd.Source -v).Trim()
    Write-Ok "npm $npmVersion"
}
else {
    Write-Warn "未找到 npm（随 Node.js 安装）"
    $Ready = $false
}

$nodeModules = Join-Path $Frontend "node_modules"
$nodeReady = (Test-Path (Join-Path $nodeModules "vite\package.json")) -and (Test-Path (Join-Path $nodeModules "react\package.json"))
$lockFile = Join-Path $Frontend "package-lock.json"
$installedLock = Join-Path $nodeModules ".package-lock.json"
if ($nodeReady -and (Test-Path $lockFile) -and (Test-Path $installedLock)) {
    if ((Get-Item $lockFile).LastWriteTimeUtc -gt (Get-Item $installedLock).LastWriteTimeUtc) {
        $nodeReady = $false
    }
}
if ($Refresh) { $nodeReady = $false }

if ($nodeReady) {
    Write-Ok "前端依赖已安装（如需更新使用 -Refresh）"
}
elseif ($Check) {
    Write-Warn "前端依赖未安装或不完整（运行 scripts\setup.ps1 安装）"
    $Ready = $false
}
elseif ($SkipInstall) {
    Write-Warn "前端依赖未安装，但指定了 -SkipInstall"
    $Ready = $false
}
elseif ($npmCmd) {
    Write-Info "安装前端依赖（npm install）…"
    Push-Location $Frontend
    try {
        & $npmCmd.Source install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "前端依赖安装失败（npm 退出码 $LASTEXITCODE）。"
            exit 1
        }
    }
    finally {
        Pop-Location
    }
    Write-Ok "前端依赖安装完成"
}

# ------------------------------------------------------------------ 可选浏览器
if ($WithBrowser) {
    if ($Check) {
        Write-Info "-Check 模式跳过 Playwright 安装"
    }
    elseif (Test-Path $VenvPy) {
        Write-Info "安装 Playwright Chromium（可选；默认演示优先使用本机 Edge）…"
        & $VenvPy -m playwright install chromium
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Playwright Chromium 安装失败；仍可使用本机 Edge（PLAYWRIGHT_CHANNEL=msedge）"
        }
        else {
            Write-Ok "Playwright Chromium 安装完成"
        }
    }
}

# ------------------------------------------------------------------ 汇总
if ($Check) {
    if ($Ready) {
        Write-Ok "环境检查通过。"
        exit 0
    }
    Write-Fail "环境尚未就绪，请运行 powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 完成安装。"
    exit 1
}

if (-not $Ready) {
    Write-Fail "部分依赖未就绪，请根据上方提示处理后重试。"
    exit 1
}

Write-Host ""
Write-Host "环境准备完成。下一步："
Write-Host "  启动开发环境（前后端一起）：powershell -ExecutionPolicy Bypass -File scripts\dev.ps1"
Write-Host "  构建：                        powershell -ExecutionPolicy Bypass -File scripts\build.ps1"
Write-Host "  后端接口文档：                http://127.0.0.1:8000/docs"
Write-Host "  演示账号：                    demo / demo123"
