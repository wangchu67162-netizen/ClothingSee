#!/usr/bin/env bash
# 衣见 ATELIER 开发启动脚本（Git Bash / MSYS2 / Linux）
#
# 一条命令同时启动：
#   后端 FastAPI  http://127.0.0.1:8000（uvicorn --reload）
#   前端 Vite     http://127.0.0.1:5173（代理 /api /static /screenshots /uploads /demo-mall）
#
# 用法：bash scripts/dev.sh
# 按 Ctrl+C 会同时停止前后端，不会留下后台服务器。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
BACKEND_PORT=8000
FRONTEND_PORT=5173

info() { printf '\033[36m[dev]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[warn]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

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

PY="$(find_venv_python || true)"
[ -n "$PY" ] || fail "未找到 backend/.venv，请先运行 bash scripts/setup.sh"
[ -f "$BACKEND/app/main.py" ] || fail "未找到 backend/app/main.py，请检查项目结构"
[ -f "$FRONTEND/node_modules/vite/package.json" ] || fail "前端依赖未安装，请先运行 bash scripts/setup.sh"
command -v npm >/dev/null 2>&1 || fail "未找到 npm，请安装 Node.js 18+"

if [ ! -f "$BACKEND/.env" ] && [ -f "$BACKEND/.env.example" ]; then
  cp "$BACKEND/.env.example" "$BACKEND/.env"
  info "已从 .env.example 生成 backend/.env（默认 Mock 模式）"
fi

port_in_use() {
  "$PY" - "$1" <<'PY'
import socket
import sys

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(0.4)
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    print("0")
else:
    print("1")
finally:
    sock.close()
PY
}

if [ "$(port_in_use "$BACKEND_PORT")" = "1" ]; then
  fail "端口 $BACKEND_PORT 已被占用。请先停止占用进程（例如上次未退出的 uvicorn）后重试。"
fi
if [ "$(port_in_use "$FRONTEND_PORT")" = "1" ]; then
  fail "端口 $FRONTEND_PORT 已被占用。请先停止占用进程（例如上次未退出的 Vite）后重试。"
fi

BACK_PID=""
FRONT_PID=""
CLEANED=0

kill_tree() {
  local pid="$1"
  local winpid=""
  [ -n "$pid" ] || return 0
  if command -v taskkill >/dev/null 2>&1; then
    # Git Bash 的 $! 是 MSYS PID，taskkill 需要 Windows PID；ps -l 第 4 列可映射。
    winpid="$(ps -l 2>/dev/null | awk -v target="$pid" '$1 == target { print $4; exit }')"
    if [ -n "$winpid" ] && [ "$winpid" != "0" ]; then
      taskkill //PID "$winpid" //T //F >/dev/null 2>&1 || true
      return 0
    fi
  fi
  kill "$pid" >/dev/null 2>&1 || true
}

# 兜底：按监听端口结束本次启动的服务（仅用于 taskkill 映射失败的场景）。
kill_port_listener() {
  local port="$1"
  command -v netstat >/dev/null 2>&1 || return 0
  command -v taskkill >/dev/null 2>&1 || return 0
  netstat -ano 2>/dev/null \
    | awk -v p=":$port" '$2 ~ (p "$") && $4 == "LISTENING" { print $5 }' \
    | sort -u \
    | while read -r winpid; do
        [ -n "$winpid" ] || continue
        case "$winpid" in *[!0-9]*) continue ;; esac
        taskkill //PID "$winpid" //T //F >/dev/null 2>&1 || true
      done
}

cleanup() {
  [ "$CLEANED" -eq 1 ] && return 0
  CLEANED=1
  trap - EXIT INT TERM
  info "正在停止前端与后端 …"
  kill_tree "$FRONT_PID"
  kill_tree "$BACK_PID"
  kill_port_listener "$FRONTEND_PORT"
  kill_port_listener "$BACKEND_PORT"
  info "前后端已停止。"
}

trap cleanup EXIT INT TERM

info "启动后端：http://127.0.0.1:$BACKEND_PORT （接口文档 /docs）"
( cd "$BACKEND" && exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload --reload-dir app ) &
BACK_PID=$!

info "启动前端：http://127.0.0.1:$FRONTEND_PORT"
( cd "$FRONTEND" && exec npm run dev ) &
FRONT_PID=$!

cat <<EOF

  前端主站   http://127.0.0.1:$FRONTEND_PORT
  后端 API   http://127.0.0.1:$BACKEND_PORT/api/meta
  接口文档   http://127.0.0.1:$BACKEND_PORT/docs
  云裳商城   http://127.0.0.1:$BACKEND_PORT/demo-mall/
  演示账号   demo / demo123

  按 Ctrl+C 同时停止前后端。

EOF

# 任一服务退出时，结束另一个并退出。
while kill -0 "$BACK_PID" >/dev/null 2>&1 && kill -0 "$FRONT_PID" >/dev/null 2>&1; do
  sleep 1
done

warn "检测到某个服务已退出，正在清理另一个进程 …"
exit 1
