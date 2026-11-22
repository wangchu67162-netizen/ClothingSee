# 衣见 ATELIER 答辩演示脚本（8–10 分钟）

> 目标：在 8–10 分钟内完整展示「登录 → 购物 → AI 荐衣 → AI 下单 → 小模型接口 / 架构」。
> 默认使用 Mock 模式，确保无网络、无 API Key 也能稳定演示；如现场 Qwen 网络稳定，可切到 Qwen 模式增加亮点。
> 本文已按 2026-11-21 的实际页面、脚本与 T17 截图更新。文中时间为预算值，实际耗时以现场为准。

## 0. 演示前检查（台下完成，不计入 10 分钟）

### 0.1 启动服务

推荐一条命令同时启动前后端（Git Bash）：

```bash
cd C:/Users/cc/Desktop/服装平台项目
bash scripts/setup.sh --check   # 首次或换机器时先检查；未就绪则执行 bash scripts/setup.sh
bash scripts/dev.sh             # 后端 :8000 + 前端 :5173；Ctrl+C 一起停止
```

PowerShell 等价命令：

```powershell
cd C:\Users\cc\Desktop\服装平台项目
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Check
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

手动启动（备用）：

```bash
# 终端 A
cd C:/Users/cc/Desktop/服装平台项目/backend
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app

# 终端 B
cd C:/Users/cc/Desktop/服装平台项目/frontend
npm run dev
```

### 0.2 检查清单

- [ ] http://127.0.0.1:8000/api/health 返回 `status: ok`。
- [ ] http://127.0.0.1:8000/api/meta 的 `mode` 为 `mock`（或确认已切到 `qwen`）；`features.browser_automation` 为 `true`。
- [ ] http://127.0.0.1:5173 首页正常，星空、玻璃、鼠标尾焰可见；首页可竖向翻 5 屏。
- [ ] 演示账号 `demo / demo123` 可登录；登录页有「使用演示账号 demo / demo123」一键填充。
- [ ] 样例图存在：`backend/app/static/images/samples/outfit-demo.webp`，并记住文件选择器中的路径。
- [ ] 本机 Microsoft Edge 可用（默认 `PLAYWRIGHT_CHANNEL=msedge`）；如不可用，提前执行 `backend/.venv/Scripts/python.exe -m playwright install chromium`。
- [ ] 浏览器缩放 100%，关闭无关弹窗与通知。
- [ ] 建议提前完整走一遍流程，确认购物车、订单、截图目录可写。
- [ ] 如需干净数据：停止后端，删除 `backend/data/app.db`，重启后端重新种子化。T17 验收在演示库中留下了测试账号、两笔订单、荐衣/助理会话与浏览任务；`scripts/e2e_full_mock.py` 还会清空 demo 购物车。
- [ ] 运行期截图目录：`backend/runtime/screenshots/<session_id>/01.png … 07.png`；长期归档截图在 `docs/screenshots/`。

### 0.3 演示模式选择

- **稳妥方案（推荐）**：`LLM_MODE=auto` + 空 Key，Mock 模式。全链路确定性，耗时稳定。
- **增强方案**：`.env` 填 `DASHSCOPE_API_KEY`，`LLM_MODE=auto`，重启后端；`/api/meta` 显示 `mode=qwen`。若现场网络抖动，随时切回 Mock 并重启。
- **已实测范围**：Mock 模式全链路 10/10 通过（见 `docs/E2E_RESULTS.md`）；真实 Qwen 路径本机未验证，演示前若启用请单独试跑。

## 1. 开场（0:00–0:30）

**做**：停留在首页第一屏，让星空、液态玻璃与品牌标题入镜。

**参考截图**：`docs/screenshots/landing-01-hero.png`

**讲**：

> 这是「衣见 ATELIER」，一个面向课程答辩的 AI 服装买手店。它不只做商品浏览和下单，还展示两条完整的 AI 链路：第一，五智能体看图荐衣；第二，单智能体通过浏览器真实操作内置的云裳商城完成下单。整个项目在没有 API Key 的情况下会进入确定性 Mock 模式，今天演示的就是一条可重复、可降级、全链路可跑通的路径。

## 2. 登录与商城浏览（0:30–2:00）

### 2.1 登录（0:30–0:50）

**做**：

1. 点击导航「登录」进入 `/auth`。
2. 点击「使用演示账号 demo / demo123」一键填充。
3. 登录成功后回到首页或商城页。

**参考截图**：`docs/screenshots/auth.png`

**讲**：

> 账号体系使用 JWT，密码用 scrypt 哈希；演示账号在首次启动时自动种子化。登录后 token 由前端统一注入到 API 与 SSE 请求。

### 2.2 首页与商品浏览（0:50–1:30）

**做**：

1. 首页竖向翻页展示 5 屏：序章 → 本季精选 → 购物助理 → 五智圆桌 → 进入衣橱。
2. 进入 `/shop`，搜索「风衣」，再按「外套」分类筛选，切换价格 / 销量排序。
3. 打开商品「暮色长风衣」详情页，展示本地 WebP 图集、面料、版型、颜色、尺码与同品类推荐。
4. 如时间允许，点「以图搜衣」展示图片搜索入口。

**参考截图**：`docs/screenshots/landing-02-collection.png`、`docs/screenshots/shop.png`、`docs/screenshots/product-detail.png`

**讲**：

> 首页和 AI 造型页使用整屏竖向翻页，商品页保持常规滚动，避免购物流程被翻页打断。商品数据共 16 件，覆盖 5 个品类，图片全部本地化，不依赖 CDN。筛选、排序、分页都由后端查询完成；以图搜衣走的是视觉小模型的切比雪夫相似检索。

### 2.3 加购与模拟结算（1:30–2:00）

**做**：

1. 在详情页选择尺码与颜色，加入购物车。
2. 进入 `/cart`，调整数量。
3. 进入 `/checkout`，填写演示收货信息，提交订单（按钮文案「提交订单（模拟支付）」）。
4. 跳转 `/orders`，展示新订单与状态「已支付」。

**参考截图**：`docs/screenshots/cart.png`、`docs/screenshots/checkout.png`、`docs/screenshots/orders.png`

**讲**：

> 这里的支付是模拟支付，提交后订单直接进入已支付状态，并清空已结算的购物车项。订单号格式是 `YJ + 时间戳 + 4 位随机数`。再次强调：这是课程演示，不接真实支付。

## 3. 过渡：系统结构一句话（2:00–2:20）

**做**：可停留在订单页，或切到架构文档中的总览图。

**讲**：

> 接下来两条 AI 链路共用同一套商品库和订单库。前面是常规电商域；后面视觉小模型负责检索、NLP-KG 小模型负责图谱扩展、大模型负责理解与评议，最后统一落到订单与截图。

## 4. AI 荐衣：五智能体看图评议（2:20–5:20）

### 4.1 上传与视觉解析（2:20–3:00）

**做**：

1. 进入 `/stylist`（需登录），第 1 屏「上传照片」。
2. 上传 `backend/app/static/images/samples/outfit-demo.webp`，或点击样例图按钮。
3. 可选填写预算「2000」、备注「通勤、秋冬」。
4. 点击「开始五智共议」，观察第 2 屏「视觉解析（看懂与检索）」中的 `vision` 阶段与视觉属性。

**参考截图**：`docs/screenshots/stylist-01-upload.png`、`docs/screenshots/stylist-02-analysis.png`

**讲**：

> 上传图片后，后端先创建荐衣会话并返回 SSE。视觉解析优先调用 `qwen-vl-max`；没有 Key 或调用失败时，使用基于图片哈希的确定性 Mock，并通过 `warning` 事件明确告诉用户已经降级。不管哪种模式，后续流程都继续。

### 4.2 小模型候选与知识图谱（3:00–3:40）

**做**：

1. 指向候选商品区：视觉相似 Top-8，并自动补齐整套搭配，最多 12 个。
2. 指向知识图谱：节点、边、`chebyshev` 标识与中文摘要。
3. 指出 T17 实测样例图产生 11 个候选、图谱默认视图 40 节点 / 137 边（全图启动预热为 167 节点 / 312 边）。

**讲**：

> 视觉小模型把图片转成 256 维向量，用切比雪夫距离检索 Top-8；NLP-KG 小模型再按品类、颜色、材质、风格、场景扩展搭配候选，并构建商品—属性—搭配关系图。这里的小模型是仓库内可运行的 stub 基线，接口保持稳定，后续可以替换成自己训练的 HTTP 服务；大模型只消费它的输出，不耦合内部结构。

### 4.3 五智能体 Round 1 / Round 2（3:40–4:40）

**做**：

1. 切到第 3 屏「五智圆桌」，指向五个智能体卡片：时尚、艺术、审美、价格、舒适度。
2. 展示 Round 1「独立评议」的独立评分与理由。
3. 展示 Round 2「第二轮互评」：每个智能体看到彼此观点，向具名同伴发言；指出 `recipients` 与 `message_type`。
4. 指出 `revision` 事件：某个智能体最多修订 2 个分数。

**参考截图**：`docs/screenshots/stylist-03-roundtable.png`

**讲**：

> 五个角色关注点不同，权重分别是时尚 0.25、艺术 0.15、审美 0.20、价格 0.20、舒适度 0.20。Round 1 各自独立评分，避免互相带偏；Round 2 主持人广播彼此观点，智能体必须向具名同伴发言，允许最多修订两个分数。聚合器不是第六个智能体，只做加权分、KG 一致性与多样性校验。T17 实测两轮各 5 条消息、共 10 条 revision。

### 4.4 最终整套穿搭（4:40–5:20）

**做**：

1. 滚动到第 4 屏「最终方案」。
2. 展示 Top3、整套 outfit（尽量外套 + 上装 + 下装 / 裙装）、中文建议与耗时 / 模式标记。
3. 指出 Mock 徽标或 Qwen 徽标；T17 实测整套合计 ¥2856。

**参考截图**：`docs/screenshots/stylist-04-final.png`

**讲**：

> 最终返回 Top3 和一套完整穿搭，而不是单件推荐；价格智能体会校验预算，聚合器会避免全部推荐同类单品。整个过程通过 SSE 流式输出，刷新后还能从会话历史回看，不会因为关掉页面就丢失结果。

## 5. AI 下单：浏览器自动化（5:20–7:20）

### 5.1 搜索与商品链接（5:20–5:50）

**做**：

1. 进入 `/assistant`。
2. 点击建议词或输入「我想买风衣」。
3. 展示带图商品链接卡：平台商品页与云裳商城商品页两个入口。

**参考截图**：`docs/screenshots/assistant.png`、`docs/screenshots/assistant-products.png`

**讲**：

> 这是一个单智能体购物助理。意图识别规则优先，Qwen 兜底；搜索类请求返回带图链接卡，同时给出平台商品页和云裳商城页面。

### 5.2 浏览器真实下单（5:50–7:00）

**做**：

1. 输入「帮我下单风衣」，或点击建议词「帮我下单暮色长风衣，M 码」。
2. 观察右侧工具时间线逐步出现 7 步：打开云裳商城 → 搜索并进入商品详情 → 选择尺码与颜色 → 进入结算页 → 填写收货信息 → 提交订单 → 下单成功。
3. 每步展示动作、状态、详情与截图缩略图；可点开截图灯箱。
4. 成功页出现后，弹出「下单成功」与订单号。
5. 切到 `/orders`，展示 `source=agent` 的新订单。

**参考截图**：`docs/screenshots/assistant-order-trace/01.png … 07.png`、`docs/screenshots/assistant-order.png`；T17 最新归档：`docs/screenshots/t17/assistant-order/01.png … 07.png`、`docs/screenshots/t17/assistant-order-success.png`

**讲**：

> 这一步不是前端假动画。后端启动 Playwright 无头 Edge，真实打开内置的云裳商城，按稳定 `data-testid` 选择器完成操作，每一步截图写入 `backend/runtime/screenshots/<session_id>/NN.png` 并通过 `/screenshots/...` 提供。商城下单接口会校验 `task_token`、服务端重新计算价格，成功后写入平台订单，`source=agent`，`external_ref` 对应商城订单号。助理还会回查平台订单，只有拿到订单号且平台确有记录，前端才会提示成功；浏览器不可用或提交失败时，会明确报错，绝不假装成功。T17 实测订单号 `YJ202611212346510445`，金额 ¥1299。

### 5.3 边界说明（7:00–7:20）

**讲**：

> 云裳商城是项目内置的模拟商城，独立视觉、原生 HTML/CSS/JS，不登录真实电商、不抓取真实平台、不进行真实支付。这样既能展示浏览器自动化的完整链路，又符合课程演示的合规边界。

## 6. 小模型接口与架构（7:20–9:00）

### 6.1 小模型接口（7:20–8:20）

**做**：

1. 打开 http://127.0.0.1:8000/docs，定位 `small-models` 分组。
2. 或直接执行：

```bash
curl -s http://127.0.0.1:8000/api/small-models/status
```

3. 演示切比雪夫距离：

```bash
curl -s -X POST http://127.0.0.1:8000/api/small-models/kg/chebyshev \
  -H "Content-Type: application/json" \
  -d '{"a":[0.1,0.2,0.3],"b":[0.4,0.1,0.2]}'
```

预期返回距离 `0.3`、相似度 `0.769231`（`1 / (1 + 0.3)`），并带公式说明。

4. 如需展示图片相似检索：

```bash
curl -s -X POST http://127.0.0.1:8000/api/small-models/vision/similar \
  -F "file=@C:/Users/cc/Desktop/服装平台项目/backend/app/static/images/samples/outfit-demo.webp" \
  -F "top_k=5"
```

**讲**：

> 小模型接口是独立交付物，不依赖大模型。视觉侧有 `embed` 与 `similar`，NLP-KG 侧有 `chebyshev`、`query`、`graph`，还有统一的 `status`。切比雪夫距离定义为各维差值的最大值，相似度是 `1 / (1 + distance)`。用户训练好自己的模型后，把 `SMALL_MODEL_MODE` 设为 `http`，配置两个服务地址即可替换 stub；如果维度变了，需要重建 embedding 表。小模型 HTTP 服务失败时默认降级回 stub，可以在状态接口和日志中看到标记。

### 6.2 架构图（8:20–9:00）

**做**：打开 `docs/architecture.md`，展示 Mermaid 总览图与五智能体时序图。

**讲**：

> 架构分为表现层、API 层、业务服务层、智能体层、模型适配层和数据层。小模型先行、大模型增强；任何外部依赖失败都有降级路径。SSE 统一使用 `fetch + ReadableStream` 解析，事件从 `session`、`stage`、`vision`、`candidates`、`kg`、`agent_round`、`agent_message`、`revision` 到 `final`、`done`，前端按事件驱动渲染，不轮询。

## 7. 收尾（9:00–9:40）

**讲**：

> 最后总结三点。第一，这是一个无 Key 也能完整跑通的全栈项目，Mock 不是假页面，而是真实的业务流。第二，AI 能力是可解释、可观察的：候选、图谱、五智能体两轮互评、分数修订、浏览器步骤和截图都在界面上可见。第三，边界清晰：模拟商城、模拟支付、小模型可替换、外部服务失败会降级，浏览器下单失败绝不造假。谢谢，欢迎提问。

## 8. 故障与备用话术

| 场景 | 处理 | 话术 |
|---|---|---|
| 现场网络差 / Qwen 超时 | 切 `LLM_MODE=mock` 并重启后端 | “项目设计了自动降级；为了演示稳定，这里使用确定性 Mock，业务链路与真实模式一致。” |
| 浏览器启动失败 | 展示中文错误，不重试造假；可改用已保存的截图 | “浏览器环境不可用时会明确报错，不会伪造订单；这正是我们的失败边界设计。” |
| 商城提交失败 | 检查后端日志与 `runtime/screenshots` 最后一步 / `99-error.png` | “失败步骤和截图会保留，方便定位；平台不会生成订单。” |
| 前端 5173 打不开 | 先运行 `bash scripts/setup.sh --check`；若已构建，直接访问 8000；否则重启 Vite | “开发模式由 Vite 代理后端；生产式由 FastAPI 托管构建产物。” |
| 端口被占用 | 关闭占用进程后重启；`dev.sh` / `dev.ps1` 会主动检测并报错 | “端口固定为 8000 / 5173，避免代理与截图地址漂移。” |
| 订单页看不到 agent 订单 | 确认收到 `order_created` 且后端无 error；刷新 `/orders` | “只有商城返回订单号且平台落库成功才会出现订单。” |
| 页面数据太乱 | 停止后端，删除 `backend/data/app.db`，重启重新种子化 | “演示库可一键重置；T17 测试数据和演示数据互不影响代码。” |
| 截图 404 | 直接访问 `http://127.0.0.1:8000/screenshots/<session_id>/01.png` 验证；确认后端运行 | “截图是运行期文件，换机器后旧会话截图不会保留。” |
| 想验证真实浏览器 | `backend/.venv/Scripts/python.exe scripts/e2e_browser_test.py --browser --headed` | “真实浏览器脚本独立于默认 pytest，失败不会影响基础测试。” |

## 9. 答辩材料截图点位（已归档）

以下文件均已在仓库 `docs/screenshots/` 中，可直接用于 PPT 或答辩材料：

| 编号 | 页面 / 时机 | 归档文件 |
|---|---|---|
| 01 | `/auth` 登录页与演示账号一键填充 | `docs/screenshots/auth.png` |
| 02 | `/` 首页第一屏 | `docs/screenshots/landing-01-hero.png` |
| 03 | `/` 本季精选 | `docs/screenshots/landing-02-collection.png` |
| 04 | `/` 购物助理 | `docs/screenshots/landing-03-assistant.png` |
| 05 | `/` 五智圆桌 | `docs/screenshots/landing-04-roundtable.png` |
| 06 | `/` 收尾屏 | `docs/screenshots/landing-05-closing.png` |
| 07 | `/shop` 商品列表 | `docs/screenshots/shop.png` |
| 08 | `/product/:id` 商品详情 | `docs/screenshots/product-detail.png` |
| 09 | `/cart` 购物袋 | `docs/screenshots/cart.png` |
| 10 | `/checkout` 模拟结算 | `docs/screenshots/checkout.png` |
| 11 | `/orders` 平台订单列表 | `docs/screenshots/orders.png` |
| 12 | `/stylist` 第 1 屏 上传照片 | `docs/screenshots/stylist-01-upload.png` |
| 13 | `/stylist` 第 2 屏 看懂与检索 | `docs/screenshots/stylist-02-analysis.png` |
| 14 | `/stylist` 第 3 屏 五智圆桌 | `docs/screenshots/stylist-03-roundtable.png` |
| 15 | `/stylist` 第 4 屏 最终方案 | `docs/screenshots/stylist-04-final.png` |
| 16 | `/assistant` 初始界面 | `docs/screenshots/assistant.png` |
| 17 | `/assistant` 带图商品链接卡 | `docs/screenshots/assistant-products.png` |
| 18 | `/assistant` 浏览器步骤 01–07 | `docs/screenshots/assistant-order-trace/01.png … 07.png` |
| 19 | `/assistant` 下单成功 | `docs/screenshots/assistant-order.png` |
| 20 | T17 真实浏览器步骤（最新） | `docs/screenshots/t17/assistant-order/01.png … 07.png` |
| 21 | T17 成功页单图 | `docs/screenshots/t17/assistant-order-success.png` |
| 22 | `/docs` 或终端 | 小模型 status / chebyshev 返回（现场演示） |
| 23 | `docs/architecture.md` | 架构图与五智能体时序图（现场演示） |

机器可读 E2E 结果：`docs/screenshots/t17/e2e-report.json`；完整验收说明：`docs/E2E_RESULTS.md`。

## 10. 可能的提问与回答要点

- **为什么是五个智能体，而不是一个？** 五个角色分别约束趋势、艺术、审美、价格、舒适度，减少单一视角偏差；Round 2 的具名互评让冲突显式化。
- **为什么用切比雪夫距离？** 取各维最大差值，直观、可解释，适合归一化后的视觉向量；KG 边权与检索共用同一公式。
- **Mock 会不会掩盖真实能力？** Mock 只替换模型输出，数据库、SSE、订单、浏览器流程都是真实的；有 Key 时同一编排直接消费 Qwen 输出。需要说明真实 Qwen 路径尚未在本机验证。
- **如何替换小模型？** 实现同名 Protocol，或设置 `SMALL_MODEL_MODE=http` 指向自训练服务；维度变化需重建 embedding。
- **浏览器自动化是否合规？** 只操作项目内置的模拟商城，不登录真实电商、不抓取真实平台、不接真实支付。
- **为什么默认用 Playwright？** Playwright 基于稳定 `data-testid` 选择器，确定性和可复现性更好，课堂演示稳定。可选 browser-use 1.x 适配器已实现（`browser_use_driver.py`，需安装 `requirements-optional.txt` 并配置 DashScope Key）；本机未安装可选包、未实测真实 Agent 执行，因此答辩默认走 Playwright。
- **没有 Edge 怎么办？** 驱动会回退 Playwright 内置 Chromium；若两者都没有，会明确报错不伪造订单，可执行 `backend/.venv/Scripts/python.exe -m playwright install chromium`。
- **测试数据会影响演示吗？** T17 全链路 E2E 与 T18 冒烟验证在演示库留下了测试账号和订单；需要干净演示时删除 `backend/data/app.db` 后重启即可。
