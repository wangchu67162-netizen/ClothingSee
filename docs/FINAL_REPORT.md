# 衣见 ATELIER 最终交付报告（T19）

> 项目根：`C:/Users/cc/Desktop/服装平台项目`
> 报告日期：2026-11-22（本机时间）
> 报告范围：课程 / 毕业设计演示版最终交付汇总。只汇总现有实现与验收证据，**不修改业务代码**。
> 事实来源：`docs/CONTRACTS.md`、`docs/E2E_RESULTS.md`、`docs/architecture.md`、`docs/CONTRACT_AUDIT.md`、`docs/browser-environment.md`、`docs/browser-automation.md`、`docs/demo-script.md`、`docs/small-model-interface.md`、`README.md`，以及 T19 本次实际运行的命令输出。

## 0. 结论摘要

- **交付状态：完成（课程演示范围）**。8 个初始 worker 任务 T1–T8 均有对应产物与验证证据。
- **无 Key（Mock）全链路可运行**：不配置 `DASHSCOPE_API_KEY` 也能完成注册登录、商品浏览、购物车、结算、五智能体荐衣、小模型检索、知识图谱、浏览器自动化下单。
- **T19 本次复验通过**：
  - 后端 `pytest`：**79 passed**，26.83 秒，退出码 0。
  - 前端 `npm run build`（含 `tsc --noEmit`）：通过，1640 modules，2.14 秒。
  - 局部 HTTP 冒烟：**10/10 通过**，退出码 0。
  - `/api/meta` 实测为 `mode=mock`、`llm_mode=auto`、`small_model_mode=stub`、`features.qwen=false`。
- **T17 历史验收已归档**：无 Key 全链路 E2E **10/10 通过**，真实 Playwright + Microsoft Edge 无头浏览器完成 7 个下单步骤，订单 `YJ202611212346510445` 以 `source=agent` 落库。
- **主代理最终独立复核（2026-11-22）**：`scripts/acceptance_check.py` **28/28 通过**，含真实 Edge 无头下单 7 步/7 截图、五智能体两轮/10 次修订、Chebyshev 3.0、订单 `source=agent` 落库；详见 `docs/MAIN_ACCEPTANCE.md`。
- **未验证项已明确隔离**：
  - 真实 Qwen（DashScope）路径未验证——本机没有 API Key。
  - 用户自训练小模型 HTTP 服务未做真实联调——仅用伪 HTTP 传输做了单元测试。
  - 默认 Playwright 引擎已实测；可选 `browser_use` 适配器已实现（`backend/app/browser/browser_use_driver.py`，依赖 `requirements-optional.txt`，需 DashScope Key），本机未安装可选包、真实 Agent 执行未实测。
  - Playwright 内置 Chromium 未安装；本机真实下单使用系统 Microsoft Edge。
  - 移动端已用 Chromium 390×844 视口模拟检查（首页/衣橱横向溢出 0px、无 pageerror，截图 `docs/screenshots/mobile-*.png`）；真机、Safari/Firefox 未验证。
- 本报告不把 Mock / Stub 的“链路通过”表述为“模型效果通过”，也不把历史记录伪装成本次复跑结果。

### 验证标记

| 标记 | 含义 |
|---|---|
| **本次复验** | 2026-11-22 由 T19 实际运行并读取输出 |
| **历史归档** | 2026-11-21 由 T15/T16/T17/T18 完成，证据在仓库文档或截图中 |
| **未验证** | 缺少 Key、外部服务、浏览器或设备，未实际执行；不声称通过 |

## 1. 已完成功能

### 1.1 基础电商

- 注册、登录、当前用户、登出；JWT Bearer 鉴权；`hashlib.scrypt` 密码哈希。
- 16 件种子商品，覆盖 5 个品类：外套 3、上装 4、连衣裙 3、下装 3、配饰 3。
- 商品搜索、分类、分页、价格 / 上新 / 销量排序、精选商品。
- 商品详情、图集、面料 / 版型 / 颜色 / 尺码、同品类推荐。
- “以图搜衣”：上传图片后经视觉小模型 embedding + 切比雪夫距离检索相似商品。
- 购物车增删改查、数量修改、库存校验。
- 结算、模拟支付、订单列表 / 详情 / 取消；订单号格式 `YJ{YYYYMMDDHHMMSS}{4 位随机}`。
- 演示账号 `demo / demo123`，首次启动自动创建商品、账号与历史演示订单。
- 本地素材：16 件商品 × 3 张 WebP（48 张商品图）、3 张主视觉、1 张样例图；不依赖外部 CDN 或远程图片。

### 1.2 五智能体看图荐衣

- 用户上传图片，可选预算与文字备注；使用样例图也可演示。
- 视觉小模型产出 256 维 embedding，按切比雪夫距离检索 Top-8 候选。
- NLP-KG 小模型抽取品类 / 颜色 / 材质 / 风格 / 场景，构建知识图谱并扩展搭配候选；去重后最多 12 个。
- 固定五个智能体：
  - `fashion` / 时尚智能体，权重 0.25
  - `art` / 艺术智能体，权重 0.15
  - `aesthetics` / 审美智能体，权重 0.20
  - `price` / 价格智能体，权重 0.20
  - `comfort` / 舒适度智能体，权重 0.20
- Round 1 五个智能体独立评分；Round 2 看到彼此观点，向具名同伴发言，最多修订 2 个分数；聚合器不是第六个智能体。
- SSE 流式事件：`session`、`stage`、`vision`、`candidates`、`kg`、`agent_round`、`agent_message`、`revision`、`final`、`warning`、`error`、`done`。
- 最终输出 Top3、整套穿搭（尽量外套 + 上装 + 下装 / 裙装）、中文建议与耗时 / 模式标记。
- T17 样例图实测：11 个候选、两轮各 5 条消息、10 条 revision、Top3、整套合计 ¥2856、`kg.metric=chebyshev`。

### 1.3 单智能体 + 浏览器自动化

- 自然语言意图：搜索 / 推荐 / 下单；规则优先，Qwen 兜底解析。
- “我想买风衣”返回带图商品链接卡，同时给出平台商品页与云裳商城商品页。
- “帮我下单风衣，M 码”由 Playwright 驱动无头浏览器打开内置云裳商城，完成：
  1. 打开云裳商城
  2. 搜索并进入商品详情
  3. 选择尺码与颜色
  4. 进入结算页
  5. 填写收货信息
  6. 提交订单
  7. 下单成功
- 每一步通过 `browse_step` 推送动作、状态、详情与截图；截图位于 `backend/runtime/screenshots/<session_id>/NN.png`，通过 `/screenshots/...` 访问。
- 商城下单接口校验 `task_token`，服务端重算金额并写入平台订单 `source=agent`、`external_ref=order_no`。
- 只有商城返回订单号且平台数据库确实存在该订单时，才发送 `order_created` 并提示“下单成功”；浏览器不可用或提交失败时返回中文 `error`，**不伪造成功**。
- T17 使用真实 Microsoft Edge 157.0.4341.60 无头浏览器完成下单，订单 ¥1299，`source=agent`，可在 `/api/orders` 查询。

### 1.4 小模型 + 大模型分层

- 小模型层只暴露 `VisionModel` / `NLPKGModel` 契约，业务通过 `factory.py` 消费，不耦合模型内部。
- 视觉 stub：Pillow 64×64，RGB/HSV 直方图 + 梯度方向 + 分块颜色矩，L2 归一化到 256 维；确定性。
- NLP-KG stub：中文词典抽取属性，视觉 embedding 的 Top-3 切比雪夫近邻建 `similar_to` 边，并补上装↔下装搭配边。
- 切比雪夫距离：`distance = max_i |a_i - b_i|`；相似度：`similarity = 1 / (1 + distance)`。
- `SMALL_MODEL_MODE=stub|http`；HTTP 模式可接用户自训练模型，失败默认降级 stub 并记录 warning。
- 大模型层：`llm/qwen.py` 调 DashScope OpenAI 兼容接口，`qwen-vl-max` 看图、`qwen-plus` 文本评议；无 Key 或调用失败降级确定性 Mock。
- Mock 评分基于图片 sha256、商品 id、智能体 id 生成，五个角色公式不同，并生成中文互评话术；每个阶段约 100–300ms 延迟，便于观察 SSE。

### 1.5 前端视觉与交互

- 品牌：衣见 ATELIER；主题：深夜高定编辑部。
- 深空黑 + 香槟金 + 象牙白；液态玻璃、星空画布、鼠标尾焰、光标柔光、噪点覆盖。
- 首页 5 屏与 AI 造型页 4 屏使用整屏竖向翻页；商品、购物车、结算、订单保持常规滚动。
- 移动端与 `prefers-reduced-motion` 在代码中退化为普通滚动并关闭高消耗动效；**桌面截图已验证，真机未验证**。
- 路由：`/`、`/shop`、`/product/:id`、`/auth`、`/cart`、`/checkout`、`/orders`、`/assistant`、`/stylist`、`*` NotFound。
- `/cart`、`/checkout`、`/orders`、`/assistant`、`/stylist` 需登录；未登录跳转 `/auth?next=`。
- SSE 客户端使用 `fetch` + `ReadableStream`，不使用 `EventSource`，支持 Bearer、跨 chunk、心跳、取消。
- 前端顶部显示 Mock / Qwen 徽标；401 清 token 并跳转登录。

### 1.6 工程化与文档

- 一键脚本：`scripts/setup.sh` / `setup.ps1`、`scripts/dev.sh` / `dev.ps1`、`scripts/build.ps1`。
- 自检脚本：`scripts/smoke_test.py`（HTTP 冒烟）、`scripts/e2e_browser_test.py`（可选真实浏览器）、`scripts/e2e_full_mock.py`（无 Key 全链路 E2E）。
- 文档：README、架构、契约、小模型接口、浏览器自动化、演示脚本、E2E 结果、契约审计、浏览器环境报告。
- 运行期文件与数据库已加入 `.gitignore`：`backend/data/`、`backend/runtime/`、`frontend/dist/`、`node_modules/`。
- 不引入外部 CDN、Google Fonts、远程图片、真实支付或真实电商账号。

## 2. 8 个 worker 任务状态

> 说明：T19 未访问实时任务板。下表按 `docs/CONTRACTS.md` 的文件归属、仓库产物、测试文件与验收文档映射核验；状态指“交付完成”，验证边界另列。

| 任务 | 负责范围 | 交付证据 | 验证状态 |
|---|---|---|---|
| **T1 后端核心** | `routers/auth.py`、`tests/test_auth.py`；`security.py` / `deps.py` 鉴权链路 | 注册 / 登录 / me / logout；scrypt + PyJWT；`test_auth.py` 12 个用例 | **完成**：pytest 通过；冒烟测试登录 / 登录失败防护通过 |
| **T2 电商域** | `seed.py`、`catalog_data.py`、`routers/products.py`、`routers/cart.py`、`routers/orders.py`、`tests/test_catalog_cart_orders.py` | 16 件商品、5 品类、演示账号、商品搜索 / 详情 / 图片搜索、购物车、订单；16 个用例 | **完成**：pytest 通过；冒烟测试商品 / 购物车 / 下单 / 取消通过 |
| **T3 小模型** | `small_models/*`、`routers/small_models.py`、`docs/small-model-interface.md`、`tests/test_small_models.py` | 视觉 / NLP-KG Protocol、stub、HTTP 适配器、切比雪夫、6 个小模型接口；21 个用例 | **完成（stub 已验证）**：pytest + 冒烟通过；HTTP 适配器仅用伪传输单测，真实远程服务未验证 |
| **T4 大模型 / 五智能体** | `llm/*`、`agents/*`、`routers/recommend.py`、`services/recommendation.py`、`tests/test_agents_mock.py` | Qwen / Mock 客户端、prompts、消息总线、两轮编排、聚合、SSE；10 个用例 | **完成（Mock 已验证）**：pytest + T17 SSE 通过；真实 Qwen 未验证；Qwen 失败降级有单测 |
| **T5 浏览器 / 商城** | `browser/*`、`demo_mall/*`、`routers/assistant.py`、`routers/demo_mall.py`、`services/assistant.py`、`tests/test_assistant_mock.py` | 云裳商城页面与 API、Playwright 驱动、Mock 驱动、下单服务、助理 SSE；8 个用例 | **完成**：Mock 引擎 pytest 通过；T17 真实 Edge 7 步下单通过 |
| **T6 前端基础** | `frontend/src/{styles,lib,store,components/ui,components/effects,components/layout}/**`、`App.tsx`、`main.tsx`、`vite-env.d.ts` | 设计 token、玻璃组件、星空 / 尾焰 / 光标 / 噪点、PageDeck、AppShell / NavBar、api / sse、auth / cart / toast store、路由 | **完成**：`npm run build` 通过；页面截图归档 |
| **T7 前端电商页** | `pages/{Auth,Shop,ProductDetail,Cart,Checkout,Orders}.tsx`、`components/product/**` | 登录注册、商品列表 / 筛选 / 以图搜衣、详情、购物车、结算、订单；商品卡片 / 图集 / 网格 | **完成**：构建通过；HTTP 冒烟覆盖后端接口；页面截图归档 |
| **T8 前端 AI 页** | `pages/{Landing,Assistant,Stylist}.tsx`、`components/ai/**` | 首页 5 屏、AI 造型 4 屏、助理控制台；Agent 卡片 / 圆桌记录 / 工具轨迹 / 商品链接卡 / 上传 / KG 图 | **完成**：构建通过；T17 助理与荐衣流程通过；页面截图归档 |

**汇总：8/8 完成。** 其中 T3 的“真实远程小模型服务”、T4 的“真实 Qwen”属于外部依赖验证边界，不是代码交付缺失。

### 2.1 文档可证的后续验收节点

| 节点 | 产物 | 结论 |
|---|---|---|
| T15 契约审计 | `docs/CONTRACT_AUDIT.md` | 32 个 HTTP 操作全部存在；4 个 MISMATCH、2 个 MISSING（见“已知问题”） |
| T16 浏览器环境探测 | `docs/browser-environment.md` | Edge `channel=msedge` 无头启动成功；内置 Chromium 未安装 |
| T17 无 Key 全链路 E2E | `docs/E2E_RESULTS.md`、`docs/screenshots/t17/`、`backend/runtime/t17-e2e-run2.log` | 10/10 通过；真实 Edge 下单并落库 |
| T18 文档最终验收 | `README.md`、`docs/architecture.md`、`docs/demo-script.md`、`docs/browser-automation.md` | pytest 79、构建通过、冒烟 10/10 复跑记录 |
| T19 最终交付报告 | 本文件 | 只写文档；复验 pytest / build / smoke，未复跑 full E2E |

## 3. 文件地图

### 3.1 顶层结构

```text
C:/Users/cc/Desktop/服装平台项目/
├─ README.md                         # 安装、启动、演示、API、常见问题
├─ docs/
│  ├─ CONTRACTS.md                   # 并行开发接口契约（唯一事实来源）
│  ├─ CONTRACT_AUDIT.md              # T15 契约审计
│  ├─ architecture.md                # 架构、时序、SSE、降级矩阵
│  ├─ small-model-interface.md       # 小模型 Python / HTTP 契约
│  ├─ browser-automation.md          # 云裳商城与 Playwright 流程
│  ├─ browser-environment.md         # T16 浏览器环境探测
│  ├─ demo-script.md                 # 8–10 分钟答辩演示脚本
│  ├─ E2E_RESULTS.md                 # T17 无 Key 全链路验收
│  ├─ FINAL_REPORT.md                # 本报告（T19）
│  ├─ assets-contact-sheet.webp      # 素材联络表
│  └─ screenshots/                   # 33 张长期归档截图 + E2E JSON
├─ scripts/
│  ├─ setup.sh / setup.ps1           # 环境准备
│  ├─ dev.sh / dev.ps1               # 同时启动前后端
│  ├─ build.ps1                      # 后端导入检查 + 前端构建
│  ├─ fetch_assets.py                # 本地素材生成 / 下载
│  ├─ smoke_test.py                  # HTTP 冒烟（需后端已启动）
│  ├─ e2e_browser_test.py            # 可选真实浏览器 E2E（默认跳过）
│  └─ e2e_full_mock.py               # 无 Key 全链路 E2E（需后端已启动）
├─ backend/
│  ├─ requirements.txt               # FastAPI / SQLAlchemy / httpx / Pillow / NumPy / Playwright / pytest
│  ├─ .env.example                   # 环境变量模板；.env 已忽略
│  ├─ pytest.ini
│  ├─ app/
│  │  ├─ main.py                     # 应用入口、CORS、静态挂载、SPA 回退、lifespan 种子 + 预热
│  │  ├─ config.py                   # Pydantic Settings
│  │  ├─ database.py                 # SQLAlchemy engine / SessionLocal / init_db
│  │  ├─ models.py                   # 9 张表
│  │  ├─ schemas.py                  # Pydantic 契约
│  │  ├─ security.py                 # scrypt + PyJWT
│  │  ├─ deps.py                     # get_current_user / get_optional_user
│  │  ├─ seed.py / catalog_data.py   # 种子数据与 16 件商品
│  │  ├─ routers/                    # auth / products / cart / orders / small_models / recommend / assistant / demo_mall
│  │  ├─ services/                   # recommendation / assistant
│  │  ├─ llm/                        # qwen / mock / prompts
│  │  ├─ agents/                     # base / bus / personas / orchestrator
│  │  ├─ small_models/               # base / vision_stub / nlp_kg_stub / http_adapters / factory / metrics
│  │  ├─ browser/                    # base / playwright_driver / shopper / mock_driver / order_service
│  │  ├─ demo_mall/                  # 原生 HTML / CSS / JS 云裳商城
│  │  └─ static/images/              # 商品图 / 主视觉 / 样例图
│  ├─ tests/                         # 6 个测试文件，79 个用例
│  ├─ data/app.db                    # SQLite（运行时创建，git 忽略）
│  └─ runtime/                       # uploads / screenshots / 测试日志（git 忽略）
└─ frontend/
   ├─ package.json / vite.config.ts / tailwind.config.ts / tsconfig.json
   ├─ .npmrc                         # npmmirror
   ├─ public/images/fallback/        # 本地 SVG 兜底
   ├─ dist/                          # 生产构建产物
   └─ src/
      ├─ main.tsx / App.tsx
      ├─ styles/                     # tokens / glass / globals
      ├─ lib/                        # api / sse / format / cn / motion / useMeta
      ├─ store/                      # auth / cart / toast
      ├─ components/
      │  ├─ ui/                      # GlassPanel / GlassButton / GlassInput / Modal / Toast / Loader / PriceTag 等
      │  ├─ effects/                 # Starfield / FlameTrail / CursorGlow / NoiseOverlay
      │  ├─ layout/                  # AppShell / NavBar / Footer / PageDeck
      │  ├─ product/                 # ProductCard / ProductGrid / ProductGallery / ImageSearchDialog
      │  └─ ai/                      # AgentCard / AgentTranscript / ToolTrace / ProductLinkCard / UploadDrop / KGGraph 等
      ├─ pages/                      # Landing / Auth / Shop / ProductDetail / Cart / Checkout / Orders / Assistant / Stylist / NotFound
      └─ types/index.ts
```

### 3.2 规模统计

| 项目 | 数量 |
|---|---|
| 后端 Python 源码 | 9,545 行（`backend/app`，不含缓存） |
| 前端 TS/TSX/CSS 源码 | 10,034 行（`frontend/src`） |
| 后端测试 | 3,119 行，79 个用例 |
| 文档 | 10 个 Markdown（README + `docs/` 下 9 个，含本报告），共 4,177 行 |
| 截图 | 33 张 PNG，均可正常读取；页面截图为 1440×900 等，浏览器轨迹为 1280×900 |
| 商品 | 16 件，5 个品类；48 张商品 WebP + 3 张主视觉 + 1 张样例图 |

## 4. 测试、构建与 E2E 结果

### 4.1 T19 本次复验（2026-11-22）

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端全量测试 | `cd C:/Users/cc/Desktop/服装平台项目/backend && .venv/Scripts/python.exe -m pytest --disable-warnings` | **79 passed**，50 warnings，26.83s，退出码 0 |
| 前端类型检查 + 构建 | `cd C:/Users/cc/Desktop/服装平台项目/frontend && npm run build` | `tsc --noEmit` 通过；Vite 6.4.6，1640 modules，2.14s；退出码 0 |
| 局部 HTTP 冒烟 | 后端运行后：`backend/.venv/Scripts/python.exe scripts/smoke_test.py` | **10/10 通过**，退出码 0 |
| 运行时元信息 | `GET http://127.0.0.1:8000/api/meta` | `mode=mock`、`llm_mode=auto`、`small_model_mode=stub`、`features.qwen=false` |
| 服务清理 | 停止 uvicorn 后检查 8000 端口 | 已释放，无长期运行服务器 |

**pytest 用例分布：**

| 测试文件 | 用例数 | 对应任务 |
|---|---:|---|
| `tests/test_auth.py` | 12 | T1 |
| `tests/test_catalog_cart_orders.py` | 16 | T2 |
| `tests/test_small_models.py` | 21 | T3 |
| `tests/test_agents_mock.py` | 10 | T4 |
| `tests/test_assistant_mock.py` | 8 | T5 |
| `tests/test_integration_mock.py` | 12 | T9 集成 |
| **合计** | **79** | — |

**冒烟测试明细（T19 实测）：**

- 健康检查 `/api/health`
- 元信息 `/api/meta`
- 注册 / 登录 / 当前用户
- 登录失败防护
- 商品列表 / 搜索 / 分类 / 详情
- 以图搜衣（视觉小模型）
- 购物车增改查
- 下单 / 订单列表 / 取消
- 小模型状态 / 切比雪夫 3.0 / 视觉 / 图谱
- 云裳商城商品接口

**构建产物：**

- `frontend/dist/index.html`（0.77 kB）
- `frontend/dist/assets/index-D6ZrqeEC.css`（55.91 kB）
- `frontend/dist/assets/index-BnfK8Yxh.js`（231.73 kB）
- `frontend/dist/assets/react-vendor-aapb3dUD.js`（165.62 kB）
- `frontend/dist/assets/state-vendor-mcEAqmbU.js`（0.64 kB）

**pytest 告警说明：** 仅有 Starlette `TestClient` 与 httpx 的弃用提示、PyJWT 对默认 20 字节开发密钥的长度提示；均不影响测试结果，但属于已知改进项。

### 4.2 历史验收记录（2026-11-21）

| 检查 | 结果 | 证据 |
|---|---|---|
| T17 无 Key 全链路 E2E | **10/10 通过** | `docs/E2E_RESULTS.md`、`docs/screenshots/t17/e2e-report.json`、`backend/runtime/t17-e2e-run2.log` |
| T17 真实浏览器下单 | 真实 Playwright + Microsoft Edge 无头，7 步全部 done | 订单 `YJ202611212346510445`，`source=agent`，`status=paid`，¥1299 |
| T17 五智能体 SSE | 候选 11、两轮各 5 条消息、10 条 revision、Top3 + 整套 ¥2856 | `docs/screenshots/t17/e2e-report.json` |
| T15 契约审计 | 32 个 HTTP 操作全部存在；4 个 MISMATCH、2 个 MISSING | `docs/CONTRACT_AUDIT.md` |
| T16 浏览器环境 | Edge 157.0.4341.60 无头启动成功；内置 Chromium 未安装 | `docs/browser-environment.md` |
| T18 文档验收 | pytest 79、构建通过、冒烟 10/10 | `README.md`、`docs/architecture.md` |

### 4.3 已验证

- **基础电商全流程**：注册、登录、商品、购物车、结算、订单、取消；由 pytest + 冒烟 + T17 覆盖。
- **Mock 模式五智能体荐衣**：SSE 事件顺序、事件 id、候选、两轮互评、revision、Top3、outfit、落库；由 pytest + T17 + 页面截图覆盖。
- **Mock 模式购物助理**：意图、商品卡、步骤、下单、订单落库；由 pytest 覆盖。
- **真实浏览器下单**：T17 用系统 Edge 真实打开内置云裳商城完成 7 步并落库；截图已归档。
- **小模型 stub 接口**：`status`、`vision/embed`、`vision/similar`、`kg/chebyshev`、`kg/query`、`kg/graph`；由 pytest + 冒烟 + T17 覆盖。
- **前端生产构建**：类型检查与 Vite 构建通过。
- **页面视觉**：18 张桌面页面截图可读；首页、商品、购物车、结算、订单、助理、造型师页面均有归档。
- **降级路径（单元级）**：Qwen 失败降级 Mock、浏览器不可用不伪造订单、小模型 HTTP 失败回退 stub，均有测试。

### 4.4 未验证

- **真实 Qwen 路径**：本机 `DASHSCOPE_API_KEY` 为空，`/api/meta` 显示 `qwen=false`；未实际调用 `qwen-vl-max` / `qwen-plus`，未验证真实 JSON 质量、限流与网络超时行为。
- **真实远程小模型 HTTP 服务**：`HttpVisionModel` 等适配器只用伪 httpx 传输做了单元测试；没有启动用户侧 `/embed`、`/rank`、`/extract` 服务做联调。
- **`browser_use` 引擎**：适配器已实现（`browser_use_driver.py`），但依赖 `browser-use==1.0.3` 的可选安装与 DashScope Key；本机未安装、未实测。缺少依赖/Key 时返回中文错误，或按配置回退 Playwright。默认 Playwright 路径已实测。
- **Playwright 内置 Chromium**：本机未安装；真实浏览器验证使用系统 Edge。
- **移动端真机 / Safari / Firefox**：没有自动化或真机证据；响应式与 reduced-motion 仅有代码实现与桌面截图。
- **模型效果质量**：Stub embedding、Mock 评分只验证链路与契约，不代表真实检索精度或评议质量。
- **真实支付 / 真实电商平台**：明确不在项目范围；云裳商城为模拟商城，支付为模拟支付。
- **T19 全链路 E2E 复跑**：T19 只复跑了 pytest / build / smoke；full E2E 引用 T17 归档结果。若现场需要重新生成证据，可运行 `scripts/e2e_full_mock.py`。

## 5. 截图索引

全部长期归档位于 `C:/Users/cc/Desktop/服装平台项目/docs/screenshots/`，共 33 张 PNG。T19 已用 Pillow 逐张读取验证，无损坏文件。

### 5.1 页面截图

| 页面 | 截图路径 |
|---|---|
| 首页 Hero | `docs/screenshots/landing-01-hero.png` |
| 首页 精选系列 | `docs/screenshots/landing-02-collection.png` |
| 首页 AI 造型师 | `docs/screenshots/landing-03-assistant.png` |
| 首页 五智能体圆桌 | `docs/screenshots/landing-04-roundtable.png` |
| 首页 收尾 | `docs/screenshots/landing-05-closing.png` |
| 登录 / 注册 | `docs/screenshots/auth.png` |
| 商品列表 | `docs/screenshots/shop.png` |
| 商品详情 | `docs/screenshots/product-detail.png` |
| 购物车 | `docs/screenshots/cart.png` |
| 结算 | `docs/screenshots/checkout.png` |
| 订单 | `docs/screenshots/orders.png` |
| 助理首页 | `docs/screenshots/assistant.png` |
| 助理商品卡 | `docs/screenshots/assistant-products.png` |
| 助理下单结果 | `docs/screenshots/assistant-order.png` |
| 造型师 上传 | `docs/screenshots/stylist-01-upload.png` |
| 造型师 视觉解析 / 候选 | `docs/screenshots/stylist-02-analysis.png` |
| 造型师 五智能体圆桌 | `docs/screenshots/stylist-03-roundtable.png` |
| 造型师 最终穿搭 | `docs/screenshots/stylist-04-final.png` |

### 5.2 T17 真实浏览器下单轨迹（最新）

| 步骤 | 截图路径 |
|---|---|
| 01 打开云裳商城 | `docs/screenshots/t17/assistant-order/01.png` |
| 02 搜索并进入商品详情 | `docs/screenshots/t17/assistant-order/02.png` |
| 03 选择尺码与颜色 | `docs/screenshots/t17/assistant-order/03.png` |
| 04 进入结算页 | `docs/screenshots/t17/assistant-order/04.png` |
| 05 填写收货信息 | `docs/screenshots/t17/assistant-order/05.png` |
| 06 提交订单 | `docs/screenshots/t17/assistant-order/06.png` |
| 07 下单成功 | `docs/screenshots/t17/assistant-order/07.png` |
| 成功页单图 | `docs/screenshots/t17/assistant-order-success.png` |
| 机器可读报告 | `docs/screenshots/t17/e2e-report.json` |

较早的一份轨迹在 `docs/screenshots/assistant-order-trace/01.png … 07.png`；最新证据以 `t17/` 为准。

运行期截图不进入仓库：`backend/runtime/screenshots/<session_id>/NN.png`，通过 `/screenshots/...` 访问，目录被 `.gitignore` 忽略。

## 6. 如何启动与演示

### 6.1 环境要求

- Windows 11；本机验证 Windows 11 Home China 10.0.26200。
- Python 3.10+；本机验证 Python 3.13.5。
- Node.js 18+；本机验证 Node 24.19.0、npm 11.17.0。
- 可选：Microsoft Edge；本机验证 Edge 157.0.4341.60。没有 Edge 时可安装 Playwright Chromium。
- 不需要 DashScope Key；默认 Mock 模式即可完整演示。

### 6.2 一键启动（推荐）

Git Bash：

```bash
cd C:/Users/cc/Desktop/服装平台项目
bash scripts/setup.sh          # 检查环境、创建 venv、安装依赖、生成 .env
bash scripts/dev.sh            # 同时启动后端 :8000 与前端 :5173
```

PowerShell：

```powershell
cd C:\Users\cc\Desktop\服装平台项目
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

`dev.sh` / `dev.ps1` 会检测 8000 与 5173 端口；端口被占用时直接报错退出，避免混用旧进程。`Ctrl+C` 同时停止前后端。

### 6.3 手动启动

终端 A（后端）：

```bash
cd C:/Users/cc/Desktop/服装平台项目/backend
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app
```

首次启动自动建表、写入 16 件商品、演示账号 `demo / demo123` 与历史订单，并预热视觉 embedding 与知识图谱。

终端 B（前端）：

```bash
cd C:/Users/cc/Desktop/服装平台项目/frontend
npm run dev
```

前端开发服务器会将 `/api`、`/demo-mall`、`/static`、`/screenshots`、`/uploads`、`/docs`、`/openapi.json`、`/redoc` 代理到 `http://127.0.0.1:8000`。

### 6.4 访问地址与演示账号

| 用途 | 地址 |
|---|---|
| 前端主站 | http://127.0.0.1:5173 |
| 后端根地址 | http://127.0.0.1:8000 |
| FastAPI 文档 | http://127.0.0.1:8000/docs |
| OpenAPI JSON | http://127.0.0.1:8000/openapi.json |
| 健康检查 | http://127.0.0.1:8000/api/health |
| 运行模式 / 功能开关 | http://127.0.0.1:8000/api/meta |
| 云裳商城 | http://127.0.0.1:8000/demo-mall/ |

演示账号：

- 用户名：`demo`
- 密码：`demo123`
- 昵称：云裳体验官
- 登录页有「使用演示账号 demo / demo123」一键填充按钮。

### 6.5 推荐演示流程（8–10 分钟）

1. **登录与首页**（约 1 分钟）：使用 demo 账号登录；展示首页 5 屏竖向翻页、星空、玻璃、鼠标尾焰。
2. **商品与购物流程**（约 1.5 分钟）：`/shop` 搜索“风衣”或分类筛选；进入详情；加入购物车；`/checkout` 模拟结算；`/orders` 查看新订单。
3. **五智能体荐衣**（约 3 分钟）：`/stylist` 上传 `backend/app/static/images/samples/outfit-demo.webp`（或页面上的样例图按钮）；观察 `vision`、`candidates`、`kg`、`round1`、`round2`、`revision`、`final` 流式输出；展示 Top3、整套穿搭与 KG 图。
4. **浏览器下单**（约 2 分钟）：`/assistant` 输入“我想买风衣”，展示带图商品卡与两个链接；再输入“帮我下单风衣，M 码”，展示 7 个浏览步骤与截图；成功页出现订单号后，到 `/orders` 查看 `source=agent` 订单。
5. **小模型接口与架构**（约 1–2 分钟）：打开 `/docs` 或 `/api/small-models/status`；说明切比雪夫距离、stub 与 HTTP 替换；展示架构图与 Mock / Qwen 模式切换。

更详细的答辩话术、时间点与故障备用话术见 `docs/demo-script.md`。

### 6.6 重置演示数据

停止后端后执行：

```bash
cd C:/Users/cc/Desktop/服装平台项目
rm -f backend/data/app.db
rm -rf backend/runtime/uploads backend/runtime/screenshots
```

再次启动后端即可重新建表并写入种子数据。若只想清理运行期文件、保留数据库，可只删除 `backend/runtime/uploads` 与 `backend/runtime/screenshots`。

### 6.7 生产式运行（可选）

```bash
cd C:/Users/cc/Desktop/服装平台项目/frontend
npm run build

cd C:/Users/cc/Desktop/服装平台项目/backend
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

后端检测到 `frontend/dist` 后会托管 `/assets` 并做 SPA 回退；直接访问 `http://127.0.0.1:8000` 即可。

## 7. Mock 与 Qwen 模式

### 7.1 模式判定

配置位于 `backend/.env`（模板为 `backend/.env.example`）：

```dotenv
LLM_MODE=auto
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_TEXT_MODEL=qwen-plus
QWEN_VL_MODEL=qwen-vl-max
LLM_TIMEOUT=90
```

| 配置 | 行为 |
|---|---|
| `LLM_MODE=auto` + Key 为空 | 自动 Mock；`/api/meta` 的 `mode=mock`、`features.qwen=false` |
| `LLM_MODE=auto` + Key 非空 | 尝试真实 Qwen；`features.qwen=true` |
| `LLM_MODE=qwen` + Key 为空 | 荐衣流发 `qwen_no_key` warning 后降级 Mock，不中断演示 |
| `LLM_MODE=mock` | 强制 Mock，即使有 Key |
| `LLM_MODE=qwen` + Key 非空 | 强制尝试真实 Qwen；失败按降级规则处理 |

T19 实测 `/api/meta`：

```json
{"app_name":"衣见 ATELIER","version":"1.0.0","mode":"mock","llm_mode":"auto",
 "small_model_mode":"stub","demo_username":"demo","demo_password":"demo123",
 "features":{"qwen":false,"browser_automation":true,"multi_agent":true,"small_model_http":false}}
```

> `demo_username` / `demo_password` 是演示项目为登录页一键填充而暴露的固定演示账号，不是真实用户凭据；生产环境不应保留该行为。

### 7.2 Mock 模式

- 五智能体评分基于图片 sha256、商品 id、智能体 id 确定性生成；五个角色公式不同。
- 生成中文互评话术；每个智能体阶段约 100–300ms 延迟，SSE 可观察。
- 视觉解析、候选、图谱、Top3、整套穿搭、浏览器步骤与订单都真实写入数据库或产生业务结果。
- Mock 不是“假页面”：电商、购物车、订单、浏览器下单链路均为真实业务流，只是模型输出是确定性的。
- 前端顶部显示 Mock 徽标。

### 7.3 启用 Qwen

编辑 `backend/.env`：

```dotenv
LLM_MODE=auto
DASHSCOPE_API_KEY=你的_DashScope_Key
```

重启后端；`/api/meta` 显示 `mode=qwen`，前端显示 Qwen 模式。相关模型：

- 图片理解：`QWEN_VL_MODEL=qwen-vl-max`
- 文本评议：`QWEN_TEXT_MODEL=qwen-plus`
- 超时：`LLM_TIMEOUT=90` 秒
- 接口：DashScope OpenAI 兼容接口

**本机未配置 Key，因此真实 Qwen 路径未验证。** 本报告不声称 Qwen 已通过。现场使用前建议单独验证一次视觉解析与五智能体评议。

### 7.4 降级与安全

- Qwen 429 / 5xx / 超时：首次 + 2 次重试；仍失败降级 Mock，并通过 SSE `warning` 给出中文提示。
- 400 / 401 / 403：不重试，直接降级或报错。
- JSON 解析失败：去除 json 代码围栏、截取首尾大括号；仍失败则降级。
- 小模型 HTTP 失败：默认回退 stub 并记录 warning；`SMALL_MODEL_FALLBACK_TO_STUB=false` 时改为中文错误。
- 浏览器不可用：明确中文 `error`，不生成假订单。
- `.env` 已被 `.gitignore` 忽略；不要把真实 API Key 写入代码、文档、截图或提交记录。
- JWT 默认密钥仅用于开发；正式部署必须更换为 32 字节以上随机值。

## 8. 小模型接口

### 8.1 Python 契约

代码位置：`backend/app/small_models/`。

```python
class VisionModel(ABC):
    name: str
    version: str
    dim: int
    async def embed(self, image: bytes) -> list[float]: ...
    async def embed_many(self, images: list[bytes]) -> list[list[float]]: ...
    def info(self) -> dict: ...

class NLPKGModel(ABC):
    name: str
    version: str
    async def extract(self, text: str) -> dict: ...
    async def rank(self, query_embedding, candidates, top_k) -> list[dict]: ...
    async def neighbors(self, product_id: int, limit: int = 6) -> list[dict]: ...
    async def build_graph(self, products, embeddings) -> dict: ...
    def chebyshev(self, a, b) -> float: ...
    def info(self) -> dict: ...
```

`candidates` 为 `[{"product_id": int, "embedding": list[float]}]`；`rank` 返回 `[{"product_id", "distance", "similarity"}]`，按 distance 升序。

### 8.2 切比雪夫距离与相似度

```text
distance = max_i |a_i - b_i|          # 等长非空向量
similarity = 1 / (1 + distance)
```

实现于 `backend/app/small_models/metrics.py`；KG 边权、相似检索与 `/api/small-models/kg/chebyshev` 共用同一公式。

### 8.3 HTTP 协议（接入用户自训练模型）

环境变量：

```dotenv
SMALL_MODEL_MODE=http
VISION_SERVICE_URL=http://127.0.0.1:9001
NLP_KG_SERVICE_URL=http://127.0.0.1:9002
SMALL_MODEL_TIMEOUT=30
SMALL_MODEL_TOKEN=
SMALL_MODEL_FALLBACK_TO_STUB=true
```

视觉服务：

```http
POST {VISION_SERVICE_URL}/embed
{"images_base64":["..."],"normalize":true}
→ {"embeddings":[[...]],"dim":256,"model_version":"..."}
```

NLP-KG 服务：

```http
POST {NLP_KG_SERVICE_URL}/rank
{"query_embedding":[...],"text":"...","candidates":[{"product_id":1,"embedding":[...]}],"top_k":8}
→ {"matches":[{"product_id":1,"distance":0.12,"similarity":0.89}],"extracted":{...}}

POST {NLP_KG_SERVICE_URL}/extract
{"text":"..."}
→ {"attributes":{...},"keywords":[...],"triples":[...]}
```

### 8.4 对外 HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/small-models/status` | 后端、模型版本、维度、模式与预热状态 |
| POST | `/api/small-models/vision/embed` | multipart `file`，返回 embedding |
| POST | `/api/small-models/vision/similar` | multipart `file` + `top_k`，按切比雪夫距离返回相似商品 |
| POST | `/api/small-models/kg/chebyshev` | `{a:[...],b:[...]}`，返回距离与相似度 |
| POST | `/api/small-models/kg/query` | `{text,top_k}`，返回三元组、相关商品、扩展词 |
| GET | `/api/small-models/kg/graph` | 知识图谱节点与边，可传 `product_id`、`limit` |

T17 实测：视觉维度 256；切比雪夫 `distance=3.0`、`similarity=0.25`；默认图谱 40 节点 / 137 边；启动预热全图 167 节点 / 312 边。

### 8.5 Stub 基线与替换

- 视觉 stub：Pillow 64×64，RGB/HSV 直方图 + 梯度方向 + 分块颜色矩，L2 归一化到 256 维；确定性；明确标注 `REPLACEABLE BASELINE`。
- NLP-KG stub：中文词典抽取品类 / 颜色 / 材质 / 风格 / 场景 / 尺码；Top-3 切比雪夫近邻建 `similar_to` 边；属性边与上装↔下装搭配边。
- 替换方式 A：实现同名 Protocol，在 `factory.py` 注册本地后端。
- 替换方式 B（推荐）：`SMALL_MODEL_MODE=http`，把训练与业务解耦。
- 模型维度变化后必须重建 `embeddings` 表；`embeddings.dim` 与 `model_version` 会随模型变化。
- 完整签名、JSON 示例、错误约定、模型目录与重建步骤见 `docs/small-model-interface.md`。

## 9. 已知问题与限制

T19 未发现阻塞交付的 P0 问题。以下问题按影响排序；均为课程演示范围内的已知边界或后续改进项。

| 级别 | 问题 | 证据 / 影响 | 建议 |
|---|---|---|---|
| P1 | **真实 Qwen 未验证** | 本机无 `DASHSCOPE_API_KEY`，`/api/meta` 为 `mode=mock`；真实视觉解析、评议质量、429 / 超时行为未实测 | 演示前用 Key 单独跑一次 `/stylist` 与 `/assistant`；保留 Mock 作为兜底 |
| P1 | **远程小模型 HTTP 服务未联调** | `tests/test_small_models.py` 用伪 httpx 传输验证适配器；没有真实 `/embed`、`/rank`、`/extract` 服务 | 用户训练模型后按 `docs/small-model-interface.md` 启服务并联调；先保持 `SMALL_MODEL_FALLBACK_TO_STUB=true` |
| P1 | **Pydantic 422 错误为英文** | T19 实测缺字段登录返回 `{"detail":[{"msg":"Field required"}]}`；用户可见文案不满足“中文错误”要求 | 在 `main.py` 增加 `RequestValidationError` 处理器，把 `msg` / `loc` 转成中文；属于共享契约文件，需按流程修改 |
| P2 | **`browser_use` 真实执行未验证** | 适配器与可选依赖文件已实现；本机未安装 `browser-use`、无 Key，只验证了缺依赖/缺 Key 的明确失败路径 | 答辩默认用 Playwright；若现场切换 browser_use，先安装 `requirements-optional.txt` 并配置 Key，否则会得到中文错误 |
| P2 | **内置 Chromium 未安装** | `%LOCALAPPDATA%\ms-playwright` 不存在；真实下单依赖系统 Edge | 现场确认 Edge 可用；或执行 `.venv/Scripts/python.exe -m playwright install chromium` |
| P2 | **JWT 默认密钥过短** | `.env` 默认 `dev-change-me-please` 仅 20 字节，PyJWT 给出 `InsecureKeyLengthWarning` | 正式部署改为 32 字节以上随机值；演示可接受 |
| P2 | **Token 存 localStorage** | 演示可用；生产存在 XSS 风险 | 生产改 HttpOnly Cookie + CSRF 防护 |
| P2 | **SQLite + 浏览器并发 1** | 单文件数据库、单进程、`asyncio.Semaphore(1)`；不适合高并发 | 课程演示足够；生产需 PostgreSQL / 任务队列 / 多实例限流 |
| P2 | **演示库包含测试数据** | T19 冒烟后统计：users 10、products 16、orders 13、agent_sessions 16、agent_messages 106、browse_tasks 5；含 T17 / T18 / T19 测试账号与订单 | 演示前按“重置演示数据”删除 `backend/data/app.db` 并重启 |
| P2 | **前端契约命名漂移** | 实现为 `api.del`，契约写 `api.delete`；`postSSE(path, body, onEvent, options)` 与契约的 options 回调形式不一致 | 在 `api.ts` 增加 `delete` 别名，或修订 `CONTRACTS.md`；补 `docs/CONTRACT_CHANGELOG.md` |
| P2 | **OpenAPI 契约面不完整** | 小模型接口的可选 Bearer 在 `/docs` 中显示为锁图标；recommend / assistant 会话与历史接口无 `response_model` | 仅为文档层问题；可补 response model 或 OpenAPI 说明 |
| P2 | **移动端 / 跨浏览器未验证** | 没有移动端真机、Safari、Firefox 证据；截图均为桌面视口 | 答辩前如需移动端演示，现场用浏览器设备模拟并检查翻页退化；后续补 Playwright 多视口测试 |
| P3 | **演示账号经 `/api/meta` 暴露** | `demo_username` / `demo_password` 固定值；为登录页一键填充设计 | 演示项目可接受；生产应移除 |
| P3 | **历史文档中的契约增量未登记** | `MallOrderOut.status`、`revision.to_agent`、`order_created.session_id` 等为兼容增量，但缺少 `CONTRACT_CHANGELOG.md` | 补变更记录，保持“只做加法” |
| 边界 | **模拟商城 / 模拟支付** | 云裳商城是内置模拟商城；不接真实支付、真实电商账号、真实物流 | 答辩时明确说明，避免误解 |

## 10. 后续建议

### 10.1 演示前检查清单

1. 确认 `backend/.env` 的 `LLM_MODE=auto` 与 Key 状态符合预期；如果使用 Qwen，先单独验证一次 `/stylist`。
2. 确认系统 Edge 可用；或提前安装 Playwright Chromium。
3. 需要干净数据时删除 `backend/data/app.db` 并重启后端。
4. 运行 `backend/.venv/Scripts/python.exe scripts/smoke_test.py`（后端已启动）确认 10/10。
5. 运行 `frontend` 构建或直接 `npm run dev`；确认 5173 与 8000 无端口冲突。
6. 预打开关键页面与截图，准备浏览器不可用时的备用话术。

### 10.2 工程改进

- 增加中文 422 校验处理器；统一所有用户可见错误为中文。
- 在 `api.ts` 增加 `delete` 别名或修订契约；补 `docs/CONTRACT_CHANGELOG.md`。
- 为 recommend / assistant 会话接口补 `response_model`，提升 OpenAPI 可用性。
- 增加移动端视口、`prefers-reduced-motion`、Safari/Firefox 的自动化测试。
- 增加真实 Qwen 的集成测试（可用环境变量门控，默认跳过）。
- 增加真实远程小模型服务的契约测试（可用本地假服务或 Docker）。
- 生产化：更换 JWT 密钥、HttpOnly Cookie、PostgreSQL、任务队列、限流、可观测性、审计日志。
- 如确需 `browser_use` 叙事，再实现适配层并纳入依赖与测试；当前不要声称已交付。

### 10.3 模型与产品增强

- 用真实数据训练 / 替换视觉与 NLP-KG 小模型，并按契约维度重建 embedding。
- 评估视觉检索 Top-N 命中率、五智能体评分一致性与聚合稳定性。
- 增加更多商品、尺码库存、订单状态机、退款 / 售后等电商能力（仍不接真实支付）。
- 增加用户偏好记忆、历史会话推荐、搭配收藏等演示增强功能。

## 11. 交付结论

- **课程演示交付目标已完成**：无 Key 环境可完整运行；基础电商、五智能体荐衣、单智能体浏览器下单、小模型接口与文档均已交付。
- **本次 T19 复验通过**：pytest 79 passed、前端构建通过、HTTP 冒烟 10/10。
- **真实 Qwen、远程小模型服务、browser_use、内置 Chromium、移动端真机**未验证，已在第 4.4 节与第 9 节明确列出，不当作已通过结论。
- 本项目是**课程 / 毕业设计演示项目**，不是生产级电商系统；云裳商城与支付均为模拟。

## 附录 A：T19 实际运行命令

```bash
# 后端全量测试
cd C:/Users/cc/Desktop/服装平台项目/backend
.venv/Scripts/python.exe -m pytest --disable-warnings

# 前端类型检查 + 构建
cd C:/Users/cc/Desktop/服装平台项目/frontend
npm run build

# 后端启动（测试用，随后停止）
cd C:/Users/cc/Desktop/服装平台项目/backend
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 局部 HTTP 冒烟
cd C:/Users/cc/Desktop/服装平台项目
backend/.venv/Scripts/python.exe scripts/smoke_test.py

# 元信息
curl -s http://127.0.0.1:8000/api/meta

# 截图完整性检查（Pillow 读取 33 张 PNG）
backend/.venv/Scripts/python.exe - <<'PY'
from pathlib import Path
from PIL import Image
for f in sorted(Path('docs/screenshots').rglob('*.png')):
    with Image.open(f) as im:
        print(f, im.size)
PY
```

T19 测试结束后已停止 uvicorn，并确认 8000 端口释放。

## 附录 B：证据索引

| 证据 | 路径 |
|---|---|
| 项目总览与启动说明 | `C:/Users/cc/Desktop/服装平台项目/README.md` |
| 并行开发契约 | `C:/Users/cc/Desktop/服装平台项目/docs/CONTRACTS.md` |
| 架构与实测记录 | `C:/Users/cc/Desktop/服装平台项目/docs/architecture.md` |
| 契约审计（T15） | `C:/Users/cc/Desktop/服装平台项目/docs/CONTRACT_AUDIT.md` |
| 无 Key 全链路 E2E（T17） | `C:/Users/cc/Desktop/服装平台项目/docs/E2E_RESULTS.md` |
| 浏览器环境（T16） | `C:/Users/cc/Desktop/服装平台项目/docs/browser-environment.md` |
| 浏览器自动化与选择器 | `C:/Users/cc/Desktop/服装平台项目/docs/browser-automation.md` |
| 答辩演示脚本 | `C:/Users/cc/Desktop/服装平台项目/docs/demo-script.md` |
| 小模型接口 | `C:/Users/cc/Desktop/服装平台项目/docs/small-model-interface.md` |
| 页面截图 | `C:/Users/cc/Desktop/服装平台项目/docs/screenshots/` |
| T17 浏览器轨迹 | `C:/Users/cc/Desktop/服装平台项目/docs/screenshots/t17/assistant-order/` |
| T17 机器可读报告 | `C:/Users/cc/Desktop/服装平台项目/docs/screenshots/t17/e2e-report.json` |
| T17 E2E 日志 | `C:/Users/cc/Desktop/服装平台项目/backend/runtime/t17-e2e-run2.log` |
| 后端测试目录 | `C:/Users/cc/Desktop/服装平台项目/backend/tests/` |
| 前端源码 | `C:/Users/cc/Desktop/服装平台项目/frontend/src/` |

---

**报告结束。** 本报告只记录可复核的事实；未执行的外部依赖验证均明确标注为“未验证”。
