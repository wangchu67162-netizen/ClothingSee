# 无 Key 全链路 E2E 验收结果（T17）

> 执行日期：2026-11-21 23:45–23:47（本机时间）
> 环境：Windows 11 Home China 10.0.26200 + Git Bash；后端 venv Python 3.13.5；Node 24 / Vite 6
> 结论：**通过**。无 `DASHSCOPE_API_KEY`，`/api/meta` 为 Mock；全链路 10/10 检查通过；购物助理下单由真实 Playwright + Microsoft Edge 无头浏览器完成并真实落库 `source=agent`。

## 1. 环境确认

`backend/.env` 关键配置（未修改）：

```dotenv
LLM_MODE=auto
DASHSCOPE_API_KEY=
SMALL_MODEL_MODE=stub
BROWSER_ENGINE=playwright
BROWSER_HEADLESS=true
PLAYWRIGHT_CHANNEL=msedge
```

- 进程环境变量 `DASHSCOPE_API_KEY` 为空（`printenv DASHSCOPE_API_KEY` 输出 0 字节），`auto` 模式自动进入 Mock。
- 重启后端（不复用旧进程；未开启 `--reload`，测试后已关闭）：

```bash
cd C:/Users/cc/Desktop/服装平台项目/backend
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 \
  > runtime/t17-uvicorn.log 2>&1
```

- `GET /api/meta` 实测返回：

```json
{"app_name":"衣见 ATELIER","version":"1.0.0","mode":"mock","llm_mode":"auto",
 "small_model_mode":"stub","features":{"qwen":false,"browser_automation":true,
 "multi_agent":true,"small_model_http":false}}
```

`mode=mock`、`features.qwen=false` 符合无 Key 验收要求；启动日志显示小模型预热完成（商品 16、embedding 16、节点 167、边 312）。

## 2. E2E 执行命令

本轮新增可复现脚本 `scripts/e2e_full_mock.py`（仅标准库，对运行中的后端执行；真实浏览器由后端 Playwright 驱动）：

```bash
cd C:/Users/cc/Desktop/服装平台项目
PYTHONIOENCODING=utf-8 backend/.venv/Scripts/python.exe scripts/e2e_full_mock.py
```

完整输出保存在 `backend/runtime/t17-e2e-run2.log`（最终通过轮次）与 `backend/runtime/t17-e2e-run1.log`（首轮）。机器可读结果：`docs/screenshots/t17/e2e-report.json`。

## 3. 逐项结果（最终轮次）

| # | 验证项 | 结果 | 关键实测数据 |
|---|---|---|---|
| 0 | 后端健康检查 / Mock 元信息 | 通过 | `mode=mock`、`llm_mode=auto`、`small_model=stub`、`qwen=false` |
| 1 | 注册一次性账号 / 登录 demo | 通过 | 新账号注册并 `/api/auth/me` 校验；`demo/demo123` 登录成功 |
| 2 | 商品搜索与详情 | 通过 | 搜索「风衣」命中 `暮色长风衣`（id=1，sku=ys-ow-001，¥1299，S/M/L/XL） |
| 3 | 加入购物车 | 通过 | 暮色长风衣 × 1，金额 ¥1299.0 |
| 4 | 结算 / 订单列表 | 通过 | 平台订单 `YJ202611212346482121`，`status=paid`、`source=platform`；购物车已清空；列表/详情可查 |
| 5 | 小模型 status / embed / similar / chebyshev / KG | 通过 | 视觉维度 256；`embedding` 长度 256；以图搜衣按距离升序；切比雪夫 `distance=3.0`、`similarity=0.25`；KG 查询返回商品/三元组；图谱 40 节点 / 137 边 |
| 6 | 样例图五智能体 SSE | 通过 | 会话 `aa90366e2e8a440189ec73e6798bb14a`；候选 11；`session.mode=mock`；两轮各 5 条（五 agent 全覆盖）；10 条 revision；`final` 含 Top3、整套穿搭（¥2856）、中文建议、`kg.metric=chebyshev`；落库 10 条消息 |
| 7 | 助理「我想买风衣」商品卡 | 通过 | 会话 `ed520586d2ec46dea9ab89d9c572c4f6`；`intent=recommend`；商品卡 `暮色长风衣`，含 `/product/1` 与 `/demo-mall/product.html?id=1` 链接；未创建订单 |
| 8 | 助理「帮我下单风衣，M 码」 | 通过 | `intent=order`；`engine=playwright`（非 mock）；7 个 `browse_step` 全部 done 且截图可访问；订单 `YJ202611212346510445`，`source=agent`、`status=paid`、¥1299 |
| 9 | 截图归档 | 通过 | 7 张步骤截图复制到 `docs/screenshots/t17/assistant-order/` |

SSE 事件 `id` 从 1 连续递增，`Content-Type: text/event-stream`、`X-Accel-Buffering: no` 均通过断言。

## 4. 购物助理真实浏览器下单证据

浏览器引擎来自系统 Microsoft Edge（Playwright `channel=msedge`），不是 Mock：

- 后端日志（`backend/runtime/t17-uvicorn.log`）：

```text
2026-11-21 23:46:19,983 INFO yijian.browser: Launching chromium via channel=msedge
```

- 助理会话落库 `result.engine = "playwright"`；`browse_task.status = "done"`，7 个步骤：
  `打开云裳商城` → `搜索并进入商品详情` → `选择尺码与颜色` → `进入结算页` → `填写收货信息` → `提交订单` → `下单成功`。
- `GET /api/orders`（demo 登录态）核验：

```json
{"order_no":"YJ202611212346510445","status":"paid","source":"agent",
 "total":1299.0,"external_ref":"YJ202611212346510445",
 "agent_session_id":"ed520586d2ec46dea9ab89d9c572c4f6",
 "items":[{"name":"暮色长风衣","size":"M","color":"雾灰","quantity":1,"price":1299.0}]}
```

- 成功页截图可见「下单成功」「模拟支付」「订单号 YJ202611212346510445」「合计 ¥1,299」，页面明确标注云裳商城为课程演示模拟商城。

### 截图路径

长期归档（文档引用）：

| 步骤 | 路径 |
|---|---|
| 01 打开云裳商城 | `docs/screenshots/t17/assistant-order/01.png` |
| 02 搜索并进入商品详情 | `docs/screenshots/t17/assistant-order/02.png` |
| 03 选择尺码与颜色 | `docs/screenshots/t17/assistant-order/03.png` |
| 04 进入结算页 | `docs/screenshots/t17/assistant-order/04.png` |
| 05 填写收货信息 | `docs/screenshots/t17/assistant-order/05.png` |
| 06 提交订单 | `docs/screenshots/t17/assistant-order/06.png` |
| 07 下单成功 | `docs/screenshots/t17/assistant-order/07.png` |
| 成功页单图 | `docs/screenshots/t17/assistant-order-success.png` |

运行时原始路径：`backend/runtime/screenshots/ed520586d2ec46dea9ab89d9c572c4f6/01.png … 07.png`（对应 `/screenshots/{session_id}/NN.png`，脚本已逐一 HTTP 200 校验）。

## 5. 回归检查

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端全量 pytest | `cd backend && .venv/Scripts/python.exe -m pytest -v --disable-warnings --tb=no` | **79 passed**，26.78s，退出码 0 |
| 前端类型检查 + 构建 | `cd frontend && npm run build` | 通过（`tsc --noEmit` + Vite 1640 modules，2.10s） |
| API 文档 | `GET http://127.0.0.1:8000/docs` | HTTP 200 |
| 元信息 | `GET http://127.0.0.1:8000/api/meta` | HTTP 200，`mode=mock` |

pytest 仅有非阻塞告警：Starlette `TestClient` 与 httpx 的弃用提示、PyJWT 对默认 20 字节开发密钥的长度提示；均不影响功能。

## 6. 遗留问题与说明

1. **测试数据留在演示库**：本轮在 `backend/data/app.db` 中新增了一次性账号 `t17_*`、demo 用户的两笔新订单（平台 `YJ202611212346482121`、智能体 `YJ202611212346510445`）、荐衣/助理会话与浏览任务。脚本还会在加购前清空 demo 账号的购物车，请勿在需要保留购物车演示数据时运行。若需干净演示数据：停止后端 → 删除 `backend/data/app.db` → 重启后端（自动重新种子化）。
2. **未安装 Playwright 内置 Chromium**：本机 `%LOCALAPPDATA%\ms-playwright` 不存在，实际使用系统 Edge（157.0.4341.60）的 `channel=msedge`。若系统 Edge 不可用，下单会以中文 `BrowserUnavailable` 明确失败，不会伪造成功；可执行 `backend/.venv/Scripts/python.exe -m playwright install chromium` 补齐内置浏览器。
3. **默认 JWT 密钥偏短**：`.env` 中 `JWT_SECRET=dev-change-me-please` 仅 20 字节，PyJWT 给出 `InsecureKeyLengthWarning`。课程演示可接受；正式部署应改为 32 字节以上随机值。
4. **Mock/Stub 能力边界**：五智能体评议与视觉相似度均为确定性基线（stub），本轮验证的是链路、契约与落库，不是模型质量。有 Key 的 Qwen 真实路径不在 T17 范围内（本机无 Key）。
5. **E2E 脚本依赖同机后端**：`scripts/e2e_full_mock.py` 需要后端已在 `127.0.0.1:8000` 运行，并通过 `demo/demo123` 登录；它不会自行启动/停止服务，也不访问外部网络。

## 7. 结论

无 Key（Mock）模式下，注册/登录、商品搜索/详情、购物车、平台结算、订单列表、小模型接口、五智能体 SSE、购物助理商品卡与**真实浏览器下单**全部走通；订单以 `source=agent` 真实落库且可从 `/api/orders` 查询。未发现阻塞性缺陷，本轮无需修改业务代码。
