# 主代理最终独立验收记录

> 日期：2026-11-22（本机时间）
> 项目根：`C:/Users/cc/Desktop/服装平台项目`
> 目的：在 8-worker 工作流（19 个任务）结束后，由主代理重新运行测试、构建、启动全栈并做真实浏览器验收；不直接采信子代理的成功摘要。
> 可复现脚本：`scripts/acceptance_check.py`；机器可读结果：`backend/runtime/acceptance/acceptance-report.json`。

## 1. 结论

- **通过**：后端全量测试、前端类型检查与生产构建、Mock 全链路、五智能体两轮互评、小模型接口、真实 Playwright + Microsoft Edge 无头下单、订单落库与截图访问。
- **未验证（明确保留）**：真实 Qwen 路径（本机无 Key）、远程用户小模型 HTTP 服务、browser-use 真实 Agent 执行（本机未安装可选包、无 Key）、移动真机 / Safari / Firefox。
- 演示数据库已清理为只剩 `demo` 账号；演示服务当前运行在 `http://127.0.0.1:8000`。

## 2. 独立执行记录

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端全量测试 | `cd backend && .venv/Scripts/python.exe -m pytest -q` | **79 passed**，退出码 0 |
| 前端类型检查 | `cd frontend && npm run typecheck` | 通过 |
| 前端生产构建 | `cd frontend && npm run build` | 通过（1640 modules；JS 231.73KB + react-vendor 165.62KB，CSS 55.91KB） |
| 全链路验收 | `PYTHONIOENCODING=utf-8 backend/.venv/Scripts/python.exe scripts/acceptance_check.py` | **28/28 passed** |
| 运行模式 | `GET /api/meta` | `mode=mock`、`llm_mode=auto`、`small_model_mode=stub`、`qwen=false` |
| 构建版页面 | `GET /` | 200，`text/html`（后端直接托管 `frontend/dist`） |

### 28 项验收覆盖

1. 后端健康、Mock 元信息、构建版首页。
2. demo 登录、`/auth/me`。
3. 商品搜索「风衣」、商品详情、加购、平台结算、订单落库。
4. 小模型状态、视觉 embedding 256 维、以图搜衣、Chebyshev `[1,5] vs [3,2] = 3.0`。
5. 五智能体 SSE：五个固定 agent 全部发言、Round 1/2 两轮、10 条 revision、最终 Top3 + 整套穿搭 + 中文建议。
6. 购物助理推荐 SSE：返回带图商品卡。
7. 购物助理下单 SSE：**7 个 browse_step、7 张截图**，真实 Edge 无头浏览器完成；订单 `source=agent` 落库，`agent_session_id` 可追溯，截图 URL 返回 200。
8. 荐衣历史接口可访问。

本轮最新实测订单示例：

- 平台结算：`YJ202611220011497512`，`source=platform`，¥1299。
- AI 浏览器下单：`YJ202611220011524365`，`source=agent`，¥1299，7 步截图。

历史归档（T17）另有 `YJ202611212346510445` 等订单与 `docs/screenshots/t17/` 轨迹，二者不冲突。

## 3. 验收中发现并修复的问题

### 3.1 小模型 `top_k` 传参兼容

- 现象：`POST /api/small-models/vision/similar` 文档写 multipart `top_k`，前端也按 multipart 发送；后端此前只读 query，导致前端传值被忽略，固定返回默认 8 条。
- 修复：`backend/app/routers/small_models.py` 同时接受 query 与 form 的 `top_k`，form 优先。
- 验证：query `top_k=3/5` 的既有测试仍通过；multipart `top_k=4` 返回 4 条；`scripts/acceptance_check.py` 28/28 通过。

### 3.2 browser-use 缺口

- 工作流文档原先把 browser-use 标为“未实现”，与用户明确要求不符。
- 已新增 `backend/app/browser/browser_use_driver.py`（browser-use 1.x `Agent` + `ChatOpenAI` DashScope 兼容接口 + 本地 `Browser('chromium')`）与 `backend/requirements-optional.txt`；`BROWSER_ENGINE=browser_use` 时生效。
- 已验证：未安装可选包/无 Key 时抛出中文 `BrowserUnavailable`，不会伪造订单；`BROWSER_USE_FALLBACK_TO_PLAYWRIGHT=true` 时可回退。
- **未验证**：本机未安装 browser-use、无 DashScope Key，真实 Agent 下单未执行；默认 Playwright 引擎仍是已实测路径。browser-use 1.0 不提供逐步截图，适配器输出动作步骤并从 `BrowseTask` 读取订单号。

## 4. 演示库状态

清理前：10 个用户（含 `smoke_*`、`e2e_*`、`t10check`、`t17_*` 等测试账号）、13 笔订单。
清理后：

- 用户：1（`demo / demo123`，昵称「云裳体验官」）。
- 商品：16；embedding：16（256 维）。
- 订单：保留 demo 的历史/平台/AI 订单（含本轮验收订单），用于「我的订单」演示。
- 备份：`backend/runtime/app.db.pre-cleanup.bak`。
- 验收脚本会继续创建 demo 订单与会话；若需一键恢复干净种子库：停止后端 → 删除 `backend/data/app.db` → 重启（自动 seed）。

## 5. 视觉验收（主代理实际查看）

已用 Read 工具查看以下归档截图，确认不是仅靠报告描述：

- `docs/screenshots/landing-01-hero.png`：深空星空、液态玻璃导航、香槟金大字、Hero 图与 VISION 玻璃卡。
- `docs/screenshots/landing-04-roundtable.png`：五智能体卡片、已发言/已修订状态、Round 2 具名互评条。
- `docs/screenshots/stylist-04-final.png`：Top3 商品、整套穿搭、风格建议、知识图谱节点与连线。
- `docs/screenshots/assistant-order.png`：成功提示、商品卡、7 步浏览器取证与截图。
- `docs/screenshots/t17/assistant-order/07.png`：云裳商城「下单成功」模拟支付成功页。
- `docs/screenshots/mobile-landing.png` / `mobile-shop.png`：Playwright Chromium 390×844 移动视口；首页与衣橱横向溢出均为 **0px**，无 pageerror，导航折叠、商品双列、按钮可点击。
- 移动端为桌面 Chromium 设备模拟，不是真机；Safari/Firefox 仍未验证。

## 6. 如何运行/演示

```bash
cd C:/Users/cc/Desktop/服装平台项目
# 当前已有一份运行中的后端（:8000，托管构建版前端）
# 重新启动：
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
# 或 Git Bash：
bash scripts/dev.sh
```

打开 `http://127.0.0.1:8000/`（构建版）或 `http://127.0.0.1:5173/`（开发版），使用 `demo / demo123`。

推荐演示顺序：首页五屏翻页 → 衣橱/详情/加购 → 五智造型室上传样例图 → AI 购物助理「我想买风衣」→「帮我下单暮色长风衣，M 码」→ 我的订单查看 `source=agent` 订单。

## 7. 仍需用户注意

- 配好 `DASHSCOPE_API_KEY` 后，`.env` 保持 `LLM_MODE=auto` 即会切换真实 Qwen；建议先单独验证一次 `/stylist` 和 `/assistant`。
- browser-use 是可选实验引擎：`pip install -r backend/requirements-optional.txt`，设置 `BROWSER_ENGINE=browser_use`；未安装/无 Key 时不要期待它能下单。课堂演示建议默认 Playwright。
- 移动端适配已做代码与构建检查，但未做真机验证；答辩前建议用 Edge DevTools 设备模拟过一遍。
- 所有支付、商城、地址均为模拟数据；不要填写真实个人信息。
