# 并行开发契约（8 子代理必读）

> 本文件是并行实现的唯一接口事实来源。已批准总方案：`C:\Users\cc\.claude\plans\twinkling-sniffing-origami.md`。
> 只做加法扩展；不得改表名、已有字段名、已有路由前缀。需要变更契约时，先写 `docs/CONTRACT_CHANGELOG.md` 并保持向后兼容。

## 0. 环境与运行

- 项目根：`C:\Users\cc\Desktop\服装平台项目`
- 后端 venv：`backend/.venv/Scripts/python.exe`（已装 fastapi/sqlalchemy/httpx/pillow/numpy/playwright/pytest）
- 前端 Node 24 / Vite 6 / React 18 / TS 5.9 / Tailwind 3.4（依赖已安装）
- 后端：`cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app`
- 前端：`cd frontend && npm run dev`（:5173，代理 /api /static /screenshots /uploads /demo-mall）
- 默认 Mock：`backend/.env` 中 `LLM_MODE=auto` 且 Key 为空即自动 Mock；无 Key 必须完整可跑。
- 运行期文件：上传在 `backend/runtime/uploads/`，截图在 `backend/runtime/screenshots/`（**不要写进 app/ 目录，避免 uvicorn 热重载**）。
- 商品图：`backend/app/static/images/products/*.webp`，URL `/static/images/products/xxx.webp`；样例图 `/static/images/samples/outfit-demo.webp`。
- 不允许新增运行时外链/CDN/Google Fonts；所有素材本地化。

## 1. 已存在的共享契约（禁止破坏）

- `backend/app/config.py`：`settings`（含 llm_enabled、路径、CORS、JWT）
- `backend/app/database.py`：`Base`, `engine`, `SessionLocal`, `get_db`, `init_db`
- `backend/app/models.py`：User/Product/Embedding/CartItem/Order/OrderItem/AgentSession/AgentMessage/BrowseTask（字段见文件；可加字段加表，不改已有）
- `backend/app/schemas.py`：Pydantic 契约（Auth/Product/Cart/Order/小模型/Agent/Meta）
- `backend/app/security.py`：scrypt 密码 + PyJWT
- `backend/app/deps.py`：`get_current_user`, `get_optional_user`
- `backend/app/main.py`：应用入口、CORS、静态挂载、`/api/health`、`/api/meta`、SPA 回退
- 路由占位：`backend/app/routers/{auth,products,cart,orders,small_models,recommend,assistant,demo_mall}.py`
- 种子入口占位：`backend/app/seed.py::seed_if_empty(db)`

## 2. 文件归属（严禁跨文件写）

| 任务 | 所有者文件 |
|---|---|
| T1 后端核心 | `routers/auth.py`, `tests/test_auth.py`；确有必要才改 `security.py`/`deps.py` |
| T2 电商域 | `seed.py`, `routers/products.py`, `routers/cart.py`, `routers/orders.py`, `tests/test_catalog_cart_orders.py`；使用 `catalog_data.py` |
| T3 小模型 | `small_models/*`, `routers/small_models.py`, `docs/small-model-interface.md`, `tests/test_small_models.py` |
| T4 大模型/五智能体 | `llm/*`, `agents/*`, `routers/recommend.py`, `services/recommendation.py`, `tests/test_agents_mock.py` |
| T5 浏览器/商城 | `browser/*`, `demo_mall/*`, `routers/assistant.py`, `routers/demo_mall.py`, `services/assistant.py`, `tests/test_assistant_mock.py` |
| T6 前端基础 | `frontend/src/{styles,lib,store,components/ui,components/effects,components/layout}/**`, `App.tsx`, `main.tsx`, `vite-env.d.ts` |
| T7 前端电商页 | `frontend/src/pages/{Auth,Shop,ProductDetail,Cart,Checkout,Orders}.tsx`, `frontend/src/components/product/**` |
| T8 前端 AI 页 | `frontend/src/pages/{Landing,Assistant,Stylist}.tsx`, `frontend/src/components/ai/**` |
| T9+ | 集成/测试/文档/打磨，依赖门控后再改相应文件 |

共享只读：`frontend/src/types/index.ts`。若确实缺类型，追加（不重命名），在交付说明中注明。

## 3. 后端 API 契约

所有业务错误用 `HTTPException(status_code, detail="中文提示")`。鉴权 `Authorization: Bearer <JWT>`。

### 3.1 认证
| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| POST | `/api/auth/register` | `{username,password,nickname?}` | `AuthResponse` |
| POST | `/api/auth/login` | `{username,password}` | `AuthResponse` |
| GET | `/api/auth/me` | Bearer | `UserPublic` |
| POST | `/api/auth/logout` | Bearer | `{ok:true}`（客户端清 token） |

### 3.2 商品
| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| GET | `/api/products` | `q,category,sort(price_asc/price_desc/new/sales),page,page_size,featured` | `ProductListOut` |
| GET | `/api/products/categories` | — | `CategoryOut[]` |
| GET | `/api/products/{id}` | — | `ProductOut`（404 中文） |
| POST | `/api/products/search-by-image` | multipart `file` + `top_k` | `ImageSearchOut`（调 T3 视觉适配器） |

### 3.3 购物车（Bearer）
| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| GET | `/api/cart` | — | `CartOut` |
| POST | `/api/cart` | `CartAddRequest` | `CartOut` |
| PATCH | `/api/cart/{item_id}` | `{quantity}`，0=删除 | `CartOut` |
| DELETE | `/api/cart/{item_id}` | — | `CartOut` |
| DELETE | `/api/cart` | — | 空 `CartOut` |

### 3.4 订单（Bearer）
| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| POST | `/api/orders` | `OrderCreateRequest`（默认结算整个购物车；可传 item_ids） | `OrderOut`，模拟支付成功 status=paid，清空已结算项 |
| GET | `/api/orders` | — | `OrderOut[]`（新到旧） |
| GET | `/api/orders/{id}` | — | `OrderOut` |
| POST | `/api/orders/{id}/cancel` | — | `OrderOut`（仅 paid→cancelled） |

订单号格式 `YJ{YYYYMMDDHHMMSS}{4位随机}`；`source=platform|agent`。

### 3.5 小模型（除 status 外可选 Bearer）
| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| GET | `/api/small-models/status` | — | `SmallModelsStatus` |
| POST | `/api/small-models/vision/embed` | multipart `file` | `VisionEmbedResponse` |
| POST | `/api/small-models/vision/similar` | multipart `file`, `top_k=8`（query 或 form，form 优先） | `VisionSimilarResponse` |
| POST | `/api/small-models/kg/chebyshev` | `{a:[...],b:[...]}` | `ChebyshevResponse` |
| POST | `/api/small-models/kg/query` | `{text,top_k}` | `KGQueryResponse` |
| GET | `/api/small-models/kg/graph` | `product_id?,limit=60` | `KGGraphOut` |

### 3.6 五智能体荐衣（Bearer）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/recommend/image` | multipart `file`（必填）、`budget`（可选数字）、`note`（可选）；**直接返回 SSE 流** |
| GET | `/api/recommend/sessions/{id}` | `{session: AgentSessionOut, messages: AgentMessageOut[], result}` |
| GET | `/api/recommend/history` | 当前用户会话列表 |

SSE 事件（`event:` 名 + `data:` JSON，`id:` 递增）：

| event | data |
|---|---|
| `session` | `{session_id, mode:"mock"|"qwen", stages:[...]}` |
| `stage` | `{stage:"vision"|"retrieval"|"round1"|"round2"|"aggregate", label, progress}` |
| `vision` | `VisionAnalysis` |
| `candidates` | `{items: ProductOut[], metric:"chebyshev", backend}` |
| `kg` | `{nodes, edges, metric:"chebyshev", summary}` |
| `agent_round` | `{round:1|2, label}` |
| `agent_message` | AgentMessageOut 字段 + `agent_name`；`scores`/`recipients`/`message_type` 必须可见 |
| `revision` | `{agent, product_id, old_score, new_score, reason}` |
| `final` | `RecommendationFinal`（含 Top3 + outfit + advice + kg + mode + elapsed_ms） |
| `warning` | `{code, message, stage}` |
| `error` | `{code, message}` |
| `done` | `{session_id, elapsed_ms}` |

固定五智能体 id/名称：
`fashion/时尚智能体`、`art/艺术智能体`、`aesthetics/审美智能体`、`price/价格智能体`、`comfort/舒适度智能体`。
至少两轮：Round 1 独立评分；Round 2 必须看到彼此观点，向具名同伴发言，并允许修订最多 2 个分数。聚合器不是第六个智能体。

### 3.7 单智能体 + 浏览器（Bearer）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/assistant/chat` | JSON `{message, session_id?}`；**返回 SSE** |
| GET | `/api/assistant/sessions/{id}` | 会话与步骤 |
| GET | `/api/assistant/history` | 当前用户会话 |

Assistant SSE：`session` → `intent` → `assistant_message` → `products`（`{items:[{product, platform_url, mall_url}]}`）→ `browse_step`（`{index,action,status,detail,screenshot}`）→ `order_created`（`{order_no, source, total}`）→ `done`；失败 `error`/`warning`。

下单必须真实驱动无头浏览器完成云裳商城结算；成功才提示“下单成功”。浏览器不可用时明确报错，不得假装成功。测试可走 Mock 引擎。

### 3.8 云裳商城
- 页面：`/demo-mall/`、`/demo-mall/product.html?id=`、`/demo-mall/checkout.html`、`/demo-mall/success.html?order_no=`（原生 HTML/CSS/JS，独立视觉）。
- API：`GET /demo-mall/api/products?q=`、`GET /demo-mall/api/products/{id}`、`POST /demo-mall/api/orders`。
- 下单入参：`{task_token, product_id, size, color, quantity, customer:{name,phone,address}}`；服务端重算价格，校验 task_token 后创建平台 `Order(source="agent", external_ref=order_no)`，返回 `{order_no, total}`。
- 稳定选择器（Playwright 依赖）：`[data-testid="mall-search"]`、`[data-testid="mall-product-card"]`、`[data-testid="mall-product-name"]`、`[data-testid="mall-buy-now"]`、`#ship-name`、`#ship-phone`、`#ship-address`、`[data-testid="mall-place-order"]`、`[data-testid="mall-order-no"]`。

## 4. 小模型契约

### 4.1 Python（`backend/app/small_models/base.py`）
```python
class VisionModel(ABC):
    name: str; version: str; dim: int
    async def embed(self, image: bytes) -> list[float]: ...
    async def embed_many(self, images: list[bytes]) -> list[list[float]]: ...
    def info(self) -> dict: ...

class NLPKGModel(ABC):
    name: str; version: str
    async def extract(self, text: str) -> dict: ...          # attributes/keywords/triples
    async def rank(self, query_embedding, candidates, top_k) -> list[dict]: ...
    async def neighbors(self, product_id: int, limit: int = 6) -> list[dict]: ...
    async def build_graph(self, products, embeddings) -> dict: ...
    def chebyshev(self, a, b) -> float: ...
    def info(self) -> dict: ...
```
`candidates: list[{"product_id": int, "embedding": list[float]}]`；`rank` 返回 `[{"product_id", "distance", "similarity"}]`，按 distance 升序。
`metrics.py`：`chebyshev_distance(a,b)=max(|a_i-b_i|)`（等长非空，否则 ValueError）；`chebyshev_similarity(a,b)=1/(1+distance)`。
`factory.py`：`get_vision_model()`, `get_nlp_kg_model()`, `warm_up()`。`SMALL_MODEL_MODE=stub|http`；http 调远程服务，失败可降级 stub 并记录 warning。

### 4.2 Stub 基线（标注 REPLACEABLE BASELINE）
- 视觉：Pillow 64×64，RGB/HSV 直方图 + 梯度方向 + 分块颜色矩，L2 归一化到 256 维；确定性；商品 embedding 启动时算好并写 `embeddings` 表。
- NLP-KG：中文词典抽取品类/颜色/材质/风格/场景；视觉 embedding 的 Top-3 切比雪夫近邻建 `similar_to` 边；商品-属性边；查询扩展 + 返回三元组/相关商品。上装↔下装搭配边用于整套推荐。

### 4.3 远程 HTTP（用户自训练模型接入，重点交付）
环境变量：`SMALL_MODEL_MODE=http`, `VISION_SERVICE_URL`, `NLP_KG_SERVICE_URL`, `SMALL_MODEL_TIMEOUT=30`, `SMALL_MODEL_TOKEN`（可选）, `SMALL_MODEL_FALLBACK_TO_STUB=true`。

```
POST {VISION_SERVICE_URL}/embed
{"images_base64":["..."],"normalize":true}
→ {"embeddings":[[...]],"dim":256,"model_version":"..."}

POST {NLP_KG_SERVICE_URL}/rank
{"query_embedding":[...],"text":"...","candidates":[{"product_id":1,"embedding":[...]}],"top_k":8}
→ {"matches":[{"product_id":1,"distance":0.12,"similarity":0.89}],"extracted":{...}}

POST {NLP_KG_SERVICE_URL}/extract
{"text":"..."} → {"attributes":{...},"keywords":[...],"triples":[...]}
```
`docs/small-model-interface.md` 必须写清签名、JSON 示例、Chebyshev 公式、模型目录、替换步骤、维度变化后重建 embedding 的说明。

## 5. 五智能体与 Mock

- 权重：fashion .25、art .15、aesthetics .20、price .20、comfort .20（聚合器使用；可在 T4 内微调并写入文档）。
- 候选：视觉检索 Top-8 + NLP-KG 搭配置信候选（去重，最多 12）。
- Qwen：`llm/qwen.py` 用 httpx 调 DashScope OpenAI 兼容接口；`qwen-vl-max` 看图、`qwen-plus` 文本；超时 90s；429/5xx/超时重试 2 次；JSON 解析容错（去 ```json、截取首尾大括号）；失败降级 Mock 并发 `warning`。
- Mock 必须确定性（基于 image sha256 + product_id），五个智能体评分公式不同，生成中文互评话术；加 100–300ms 延迟让 SSE 可观察。
- 聚合：加权分 + KG 一致性 + 多样性；返回 Top3、整套 outfit（尽量外套+上装+下装/裙装）与中文建议；失败仍有确定性结果。

## 6. 前端契约

### 6.1 路由（`App.tsx`）
`/` Landing、`/shop`、`/product/:id`、`/cart`、`/checkout`、`/orders`、`/assistant`、`/stylist`、`/auth`（登录/注册切换）、`*` NotFound。
`/cart`、`/checkout`、`/orders`、`/assistant`、`/stylist` 需登录（未登录跳 `/auth?next=`）。Landing 可游客浏览。

### 6.2 类型与客户端
- 唯一类型源：`frontend/src/types/index.ts`（已提供；可追加，不改名）
- `src/lib/api.ts`：`api.get/post/patch/delete/upload`，自动 Bearer、401 清 token 并跳登录、错误转中文 `ApiError`。
- `src/lib/sse.ts`：`postSSE(url, body|FormData, {onEvent,onError,signal})`，fetch + ReadableStream，处理跨 chunk 的 `event:/data:/id:`，**不要用 EventSource**。
- `src/store/auth.ts` / `cart.ts` / `toast.ts`（Zustand）。
- token 存 `localStorage["yijian_token"]`；用户信息存 `localStorage["yijian_user"]`（演示可接受，README 注明 XSS 取舍）。

### 6.3 设计系统（T6 实现；其他人只用）
- 色板/字体 token 见 `src/styles/tokens.css`（已给初版）。
- 玻璃类 `.glass`, `.glass-strong`, `.glass-card`, `.btn-glass`, `.input-glass`, `.eyebrow`, `.display`, `.hairline`。
- 组件 API：
  - `<GlassPanel className? hover? as? children />`
  - `<GlassButton variant="primary"|"ghost"|"ember" size="sm"|"md"|"lg" loading? disabled? onClick? type? children />`
  - `<GlassInput label? error? icon? ...inputProps />`
  - `<PriceTag price originalPrice? size? />`
  - `<ToastHost />` + `useToast().push({type,title,message})`
  - `<PageDeck sections={[{id,label,content}]} onIndexChange? />`（首页专用）
  - `<Starfield />`, `<FlameTrail />`, `<CursorGlow />`, `<NoiseOverlay />`（全局挂载一次）
  - `<ProductCard product onAdd? />`（T7 实现，T8 可复用）
- 竖屏翻页：**仅** Landing 与 Stylist 使用 PageDeck；移动端/<768px 退化为 CSS scroll-snap；`prefers-reduced-motion` 禁用翻页动画与尾焰。Shop/Cart 等正常滚动。
- 视觉硬要求：液态玻璃、鼠标尾焰、留白星空、深空黑 + 香槟金 + 象牙白；不得使用外链字体/图片/CDN。

### 6.4 AI 页组件 API（T8 实现）
- `AgentCard {agentId, name, role, color, score?, status:"idle"|"thinking"|"done"|"revised", lastMessage?}`
- `AgentTranscript {messages: AgentMessage[], live?: boolean}`：轮次分隔、收件人标签、revision 标记；内部滚动。
- `ToolTrace {steps: BrowseStep[]}`：动作、状态、截图缩略图/灯箱。
- `ProductLinkCard {item: AssistantProductCard}`：图片、名称、价格、“打开平台/云裳商城”两个链接。
- `UploadDrop {onFile, loading?}`：拖拽/点击、预览、样例图按钮。
- `KGGraph {nodes, edges}`：轻量 SVG 力导向/环形布局，不引第三方图表库。

## 7. SSE 接入细节
- 后端响应头：`Content-Type: text/event-stream; charset=utf-8`、`Cache-Control: no-cache, no-transform`、`X-Accel-Buffering: no`；15s 心跳 `: ping`。
- 前端解析跨 chunk；每个事件按空行分隔；`data` 多行拼接。
- 后端在生成器中写 DB（阶段边界），即使客户端断开也尽量完成关键落库；捕获 `asyncio.CancelledError`。

## 8. 测试与验收
- 后端：`cd backend && .venv/Scripts/python.exe -m pytest -q`（无需 Key；Mock 模式）。
- 前端：`cd frontend && npm run typecheck && npm run build`。
- 每个任务交付必须列：改动文件、运行过的命令、结果、未解决项。
- 浏览器测试可用 `RUN_BROWSER_TESTS=1` 控制；默认不依赖 Playwright 成功。
- 严禁把真实 API Key、真实电商账号、真实支付信息写入代码或提交。

## 9. 任务池与依赖
初始 8 任务（T1–T8）按上表并行；后续 T9 集成（依赖 T1–T8）、T10 视觉/响应式打磨（依赖 T6–T8）、T11 测试+smoke+浏览器 E2E（依赖 T1–T5）、T12 文档（依赖 T9）、T13 截图验收（依赖 T9）、T14 最终无 Key/有 Key E2E（依赖 T10–T13，主代理兜底）。
每个 worker 完成后自动领取下一个 ready 任务；无 ready 任务时等待，不得抢别人的文件。
