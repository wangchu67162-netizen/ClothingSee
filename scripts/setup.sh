#!/usr/bin/env bash
# 衣见 ATELIER 一键环境准备（Git Bash / MSYS2 / Linux）
#
# 用法：
#   bash scripts/setup.sh                 完整检查并按需安装依赖
#   bash scripts/setup.sh --check         只检查环境，不做任何安装/写文件
#   bash scripts/setup.sh --skip-install  不执行 pip/npm 安装（依赖已就绪时使用）
#   bash scripts/setup.sh --refresh       强制重新安装前端依赖
#   bash scripts/setup.sh --with-browser  额外安装 Playwright Chromium（可选）
#
# 本脚本不会启动任何服务器。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
REQ_FILE="$BACKEND/requirements.txt"
ENV_FILE="$BACKEND/.env"
ENV_EXAMPLE="$BACKEND/.env.example"

CHECK=0
SKIP_INSTALL=0
REFRESH=0
WITH_BROWSER=0

for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --skip-install) SKIP_INSTALL=1 ;;
    --refresh) REFRESH=1 ;;
    --with-browser) WITH_BROWSER=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "未知参数：$arg（使用 --help 查看用法）" >&2; exit 2 ;;
  esac
done

info() { printf '\033[36m[setup]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[ ok  ]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[warn ]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[fail ]\033[0m %s\n' "$*" >&2; exit 1; }

if [ ! -d "$BACKEND" ] || [ ! -d "$FRONTEND" ]; then
  fail "项目结构不完整：未找到 backend/ 或 frontend/（当前根目录：$ROOT）"
fi

READY=1

find_venv_python() {
  if [ -x "$BACKEND/.venv/Scripts/python.exe" ]; then
    printf '%s\n' "$BACKEND/.venv/Scripts/python.exe"
    return 0
  fi
  if [ -x "$BACKEND/.venv/bin/python" ]; then
    printf '%s\n' "$BACKEND/.venv/bin/python"
    return 0
  fi
  return 1
}

# ------------------------------------------------------------------ Python / venv
PY="$(find_venv_python || true)"
if [ -z "$PY" ]; then
  if [ "$CHECK" -eq 1 ]; then
    warn "未找到 backend/.venv（运行 bash scripts/setup.sh 创建）"
    READY=0
  else
    SYSTEM_PY=""
    if command -v python >/dev/null 2>&1; then
      SYSTEM_PY="$(command -v python)"
    elif command -v python3 >/dev/null 2>&1; then
      SYSTEM_PY="$(command -v python3)"
    fi
    if [ -z "$SYSTEM_PY" ]; then
      fail "未找到 Python。请安装 Python 3.10+ 后重试。"
    fi
    info "创建虚拟环境 backend/.venv …"
    "$SYSTEM_PY" -m venv "$BACKEND/.venv"
    PY="$(find_venv_python)" || fail "虚拟环境创建失败，请检查 Python 安装。"
  fi
fi

if [ -n "$PY" ]; then
  if "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    ok "Python $("$PY" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
  else
    warn "Python 版本过低（需要 3.10+）：$("$PY" --version 2>&1)"
    READY=0
  fi

  HASH=""
  if [ -f "$REQ_FILE" ]; then
    HASH="$(sha256sum "$REQ_FILE" | awk '{print $1}')"
  fi
  MARKER="$BACKEND/.venv/.yijian-requirements.sha256"

  IMPORTS_OK=0
  if "$PY" -c 'import fastapi, uvicorn, sqlalchemy, pydantic, jwt, httpx, PIL, numpy, multipart, pytest' >/dev/null 2>&1; then
    IMPORTS_OK=1
  fi

  NEED_INSTALL=0
  if [ "$IMPORTS_OK" -eq 0 ]; then
    NEED_INSTALL=1
  elif [ -f "$MARKER" ] && [ "$(cat "$MARKER" 2>/dev/null || true)" != "$HASH" ]; then
    NEED_INSTALL=1
  fi

  if [ "$CHECK" -eq 1 ]; then
    if [ "$NEED_INSTALL" -eq 1 ]; then
      warn "后端依赖不满足 requirements.txt（运行 bash scripts/setup.sh 安装）"
      READY=0
    else
      ok "后端依赖已安装"
    fi
  elif [ "$NEED_INSTALL" -eq 0 ]; then
    if [ ! -f "$MARKER" ] && [ -n "$HASH" ]; then
      printf '%s\n' "$HASH" > "$MARKER"
    fi
    ok "后端依赖已就绪"
  elif [ "$SKIP_INSTALL" -eq 1 ]; then
    warn "后端依赖缺失，但指定了 --skip-install"
    READY=0
  else
    info "安装后端依赖（pip -r requirements.txt）…"
    "$PY" -m pip install --disable-pip-version-check -r "$REQ_FILE"
    if [ -n "$HASH" ]; then
      printf '%s\n' "$HASH" > "$MARKER"
    fi
    ok "后端依赖安装完成"
  fi
fi

# ------------------------------------------------------------------ .env
if [ -f "$ENV_FILE" ]; then
  ok "backend/.env 已存在"
elif [ "$CHECK" -eq 1 ]; then
  warn "缺少 backend/.env（运行 bash scripts/setup.sh 自动生成）"
  READY=0
elif [ -f "$ENV_EXAMPLE" ]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  ok "已从 .env.example 生成 backend/.env（默认 Mock 模式，无需 API Key）"
else
  warn "缺少 backend/.env.example，无法生成 .env"
  READY=0
fi

# ------------------------------------------------------------------ Node / npm
NODE_OK=0
NPM_OK=0
if command -v node >/dev/null 2>&1; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
  if [ "$NODE_MAJOR" -ge 18 ] 2>/dev/null; then
    ok "Node.js $(node -v)"
    NODE_OK=1
  else
    warn "Node.js 版本过低（需要 18+）：$(node -v)"
    READY=0
  fi
else
  warn "未找到 Node.js（需要 18+，推荐 Node 24）"
  READY=0
fi
if command -v npm >/dev/null 2>&1; then
  ok "npm $(npm -v)"
  NPM_OK=1
else
  warn "未找到 npm（随 Node.js 安装）"
  READY=0
fi

NODE_READY=0
if [ -f "$FRONTEND/node_modules/vite/package.json" ] && [ -f "$FRONTEND/node_modules/react/package.json" ]; then
  NODE_READY=1
fi
if [ -f "$FRONTEND/package-lock.json" ] && [ -f "$FRONTEND/node_modules/.package-lock.json" ] \
   && [ "$FRONTEND/package-lock.json" -nt "$FRONTEND/node_modules/.package-lock.json" ]; then
  NODE_READY=0
fi
if [ "$REFRESH" -eq 1 ]; then
  NODE_READY=0
fi

if [ "$NODE_READY" -eq 1 ]; then
  ok "前端依赖已安装（如需更新使用 --refresh）"
elif [ "$CHECK" -eq 1 ]; then
  warn "前端依赖未安装或不完整（运行 bash scripts/setup.sh 安装）"
  READY=0
elif [ "$SKIP_INSTALL" -eq 1 ]; then
  warn "前端依赖未安装，但指定了 --skip-install"
  READY=0
elif [ "$NPM_OK" -eq 1 ]; then
  info "安装前端依赖（npm install）…"
  ( cd "$FRONTEND" && npm install --no-audit --no-fund )
  ok "前端依赖安装完成"
fi

# ------------------------------------------------------------------ 可选浏览器
if [ "$WITH_BROWSER" -eq 1 ]; then
  if [ "$CHECK" -eq 1 ]; then
    info "--check 模式跳过 Playwright 安装"
  elif [ -n "$PY" ]; then
    info "安装 Playwright Chromium（可选；默认演示优先使用本机 Edge）…"
    if "$PY" -m playwright install chromium; then
      ok "Playwright Chromium 安装完成"
    else
      warn "Playwright Chromium 安装失败；仍可使用本机 Edge（PLAYWRIGHT_CHANNEL=msedge）"
    fi
  fi
fi

# ------------------------------------------------------------------ 汇总
if [ "$CHECK" -eq 1 ]; then
  if [ "$READY" -eq 1 ]; then
    ok "环境检查通过。"
    exit 0
  fi
  fail "环境尚未就绪，请运行 bash scripts/setup.sh 完成安装。"
fi

if [ "$READY" -ne 1 ]; then
  fail "部分依赖未就绪，请根据上方提示处理后重试。"
fi

cat <<'EOF'

环境准备完成。下一步：
  启动开发环境（前后端一起）：bash scripts/dev.sh
  仅构建前端生产包：          cd frontend && npm run build
  后端接口文档：              http://127.0.0.1:8000/docs
  演示账号：                  demo / demo123
EOF
