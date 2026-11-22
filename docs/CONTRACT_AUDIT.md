# API 契约审计（T15）

> 审计对象：`衣见 ATELIER` 课程演示项目
> 审计日期：2026-11-21（当前工作区快照；并行任务后续改动可能使本报告部分内容过时）
> 审计基准：`docs/CONTRACTS.md`（唯一接口事实来源）
> 审计范围：`backend/app/routers/**`、`backend/app/schemas.py`、`backend/app/main.py`、`backend/app/deps.py`、
> 前端 `frontend/src/lib/api.ts`、`frontend/src/lib/sse.ts`，以及生成 SSE 的 `backend/app/services/**`、
> `backend/app/agents/**`、`backend/app/demo_mall/**`。
> 审计方式：静态逐行比对 + FastAPI OpenAPI 导出 + TestClient 进程内 HTTP 冒烟 + 后端全量 pytest + 前端 `tsc --noEmit`。
> 本文件只记录审计结论，未修改任何业务代码。

## 0. 结论摘要

- 契约中的 **32 个 HTTP 操作全部存在**，路径、方法、前缀均正确。
- 重点区域（categories 路由顺序、Cart PATCH、图片搜索、recommend SSE、assistant SSE、demo mall 下单字段）**功能契约全部 PASS**。
- 发现 **4 个 MISMATCH**：
  1. Pydantic 自动参数校验的 422 错误为英文，违反“中文错误”要求（影响用户可见文案，优先级最高）。
  2. 前端 `api.delete` 实际实现为 `api.del`。
  3. 前端 `postSSE` 的签名/`onError` 与契约描述不一致。
  4. OpenAPI 将“可选 Bearer”的小模型接口标注为需要 Bearer（仅文档层面，运行时允许匿名）。
- 发现 **2 个 MISSING（低优先级）**：
  1. `docs/CONTRACT_CHANGELOG.md` 不存在，但已有若干向后兼容的增量字段。
  2. recommend/assistant 的会话与历史接口没有 `response_model`，OpenAPI 中响应结构为空（运行时结构正确）。
- 未发现缺失端点、错误的 HTTP 方法、SSE 事件名错误或 demo mall 下单字段错位。
- 验证结果：后端 `pytest` **79 passed**；前端 `tsc --noEmit` 通过；进程内 HTTP 冒烟全部符合预期（详见第 9 节）。
- 说明：MISMATCH/MISSING 按“根因”计数；同一个根因（如 422 中文缺失）可能在多个接口的检查项中重复出现。

状态定义：

| 状态 | 含义 |
|---|---|
| PASS | 与契约一致（兼容增量字段单独注明） |
| MISMATCH | 实现或前端客户端与契约描述不一致，需要修复或修订契约 |
| MISSING | 契约要求存在但实现/文档缺失，或 OpenAPI 契约面缺失 |

---

## 1. 重点区域逐项核对

### 1.1 categories 路由顺序 — PASS

| 检查项 | 证据 | 结论 |
|---|---|---|
| `/api/products/categories` 注册在 `/api/products/{product_id}` 之前 | `backend/app/routers/products.py:97-110`（categories），`:252-257`（`/{product_id}`）；注释 `:97` 明确说明顺序原因 | PASS |
| 运行时不把 `categories` 解析成 `product_id` | 进程内 GET `/api/products/categories` 返回 `200` 与 5 个分类计数；未返回 422 | PASS |
| 返回类型 | `list[CategoryOut]`，字段 `name/count`，见 `backend/app/schemas.py:74-77` | PASS |
| 前端调用 | `frontend/src/pages/Shop.tsx:43` 使用 `/products/categories` | PASS |

修复建议：无。保持“静态路径先于动态路径”的注册顺序即可。

### 1.2 Cart PATCH — PASS

| 检查项 | 证据 | 结论 |
|---|---|---|
| 方法/路径 | `PATCH /api/cart/{item_id}`，`backend/app/routers/cart.py:117-138` | PASS |
| 鉴权 | `Depends(get_current_user)`，`cart.py:121`；未登录返回 401 `{"detail":"请先登录"}`（已冒烟） | PASS |
| 请求字段 | `CartUpdateRequest.quantity: int (0..20)`，`backend/app/schemas.py:94-95` | PASS |
| `quantity=0` 删除 | `cart.py:125-128` 执行 `db.delete(item)` 并返回最新 `CartOut` | PASS |
| 库存校验 | `cart.py:130-135`，超出库存返回中文 400 | PASS |
| 响应 | `CartOut`（含 `items/total_quantity/total_amount`），`schemas.py:111-122` | PASS |
| 前端调用 | `frontend/src/store/cart.ts:65` 发送 `{quantity}` | PASS |
| 契约测试 | `backend/tests/test_catalog_cart_orders.py:365-380` 覆盖更新与 `quantity=0` 删除 | PASS |

修复建议：无。注意 `quantity` 上限为 20（schema 与 `MAX_QUANTITY` 一致），契约未写上限，可在后续契约修订时补充。

### 1.3 图片搜索 — PASS

| 检查项 | 证据 | 结论 |
|---|---|---|
| 方法/路径 | `POST /api/products/search-by-image`，`backend/app/routers/products.py:139-249` | PASS |
| 请求格式 | multipart：`file` 必填、`top_k` Form 字段（默认 8，1..20），`products.py:140-143`；OpenAPI 已验证为 `multipart/form-data` | PASS |
| 鉴权 | 契约未要求 Bearer，实现未依赖用户 | PASS |
| 响应类型 | `ImageSearchOut`：`items/distance_metric/backend/vision`，`schemas.py:79-83`；实测返回这四个键 | PASS |
| 实际检索结果 | 使用样例图实测返回 3 条（`top_k=3`），`distance_metric=chebyshev`、`backend=stub`，`items[].similarity` 有值 | PASS |
| 降级 | 视觉模型未就绪/加载失败返回中文 503；图片为空/过大返回中文 400/413，`products.py:145-176` | PASS |
| 前端请求字段 | `ImageSearchDialog.tsx:119-123` 发送 `file` 与 `top_k=8`，与后端 Form 字段一致 | PASS |
| 路由顺序 | POST 与 GET `/{product_id}` 不冲突；静态路径注册在前 | PASS |

修复建议：无。若后续统一小模型接口，可把 `top_k` 的 Form/Query 位置写进契约以免歧义。

### 1.4 recommend SSE — PASS

| 检查项 | 证据 | 结论 |
|---|---|---|
| `POST /api/recommend/image` 直接返回 SSE | `backend/app/routers/recommend.py:119-147`；`StreamingResponse` `:143-147` | PASS |
| 鉴权 | `Depends(get_current_user)`，`recommend.py:124`；未登录实测 401 中文 | PASS |
| 请求字段 | multipart `file` 必填、`budget` 可选、`note` 可选，`recommend.py:121-123`；`budget` 为字符串 Form，服务端再解析为数字，非法值返回中文 400（`:41-57`） | PASS（见 8.1 类型说明） |
| 会话详情 | `GET /api/recommend/sessions/{id}` 返回 `{session, messages, result}`，`recommend.py:156-179` | PASS |
| 历史 | `GET /api/recommend/history` 返回当前用户 stylist 会话数组，`recommend.py:182-200` | PASS |
| SSE 响应头 | `Cache-Control: no-cache, no-transform`、`X-Accel-Buffering: no`，`recommend.py:33-38`；Starlette 自动补 `Content-Type: text/event-stream; charset=utf-8`（已实例验证） | PASS |
| 事件 id 递增 | `_sse_wrapper` 从 1 递增，`recommend.py:91-106`；测试 `test_agents_mock.py:413-415` 严格断言 1..n | PASS |
| 15s 心跳 | `recommend.py:95-98` 发送 `: ping` | PASS |
| 事件名齐全 | `session/stage/vision/candidates/kg/agent_round/agent_message/revision/final/warning/error/done` 全部由 `services/recommendation.py` 发出（见 2.7 事件表） | PASS |
| 事件 payload | 与契约逐项一致；`revision` 多一个 `to_agent`、`final` 字段完整（Top3 + outfit + advice + kg + mode + elapsed_ms） | PASS（兼容增量） |
| 客户端消费 | `frontend/src/pages/Stylist.tsx:184-278` 处理全部事件；`AgentTranscript` 可显示 `scores/recipients/message_type` | PASS |
| 客户端解析 | `frontend/src/lib/sse.ts` 处理跨 chunk、CRLF、多行 `data`、`id`，未使用 EventSource | PASS |
| 测试 | `backend/tests/test_agents_mock.py:391-505` 覆盖事件顺序、id、payload 与落库 | PASS |

修复建议：无功能修复。建议把 `budget` 在 OpenAPI 中描述为“数字字符串”，或改为 `float | None = Form(...)`（需同时补齐中文 422 处理，见 5.1）。

### 1.5 assistant SSE — PASS

| 检查项 | 证据 | 结论 |
|---|---|---|
| `POST /api/assistant/chat` 返回 SSE | `backend/app/routers/assistant.py:23-52`；`StreamingResponse` `:48-52` | PASS |
| 鉴权 | `Depends(get_current_user)`，`assistant.py:27` | PASS |
| 请求字段 | JSON `AssistantChatRequest {message, session_id?}`，`schemas.py:319-322`；前端 `Assistant.tsx:198-203` 发送同名字段 | PASS |
| 会话详情 | `GET /api/assistant/sessions/{id}` 返回 `session/messages/browse_task/result`，`assistant.py:63-72`、`services/assistant.py:873-891` | PASS |
| 历史 | `GET /api/assistant/history` 返回 `{items:[...]}`，`assistant.py:55-60` | PASS（契约未规定外层形状） |
| 事件顺序 | `session → intent → assistant_message → products → browse_step* → order_created → done`，`services/assistant.py:626-821` | PASS |
| `products` payload | `{items:[{product, platform_url, mall_url}]}`，`services/assistant.py:221-229`；测试 `test_assistant_mock.py:227-234` 断言两个 URL | PASS |
| `browse_step` payload | 严格为 `{index, action, status, detail, screenshot}`，`services/assistant.py:427-442, 725-733` | PASS |
| `order_created` payload | `{order_no, source:"agent", total}`，另含兼容字段 `session_id`，`services/assistant.py:752-760` | PASS（兼容增量） |
| 下单真实性 | 只有 `_verify_order` 在平台库找到订单后才发 `order_created`，`services/assistant.py:445-455, 737-760`；浏览器失败发 `error`，不会伪造成功 | PASS |
| 失败事件 | `error {code,message}` 中文；`done {session_id,elapsed_ms,status}`，`services/assistant.py:767-821` | PASS |
| 响应头/心跳 | `Cache-Control`、`X-Accel-Buffering`、`Connection`，`assistant.py:16-20`；媒体类型 `text/event-stream; charset=utf-8`，`:50`；15s `: ping`，`services/assistant.py:583-588` | PASS |
| 客户端消费 | `frontend/src/pages/Assistant.tsx:83-177` 处理全部事件；`ToolTrace` 接收 `BrowseStep[]` | PASS |
| 测试 | `backend/tests/test_assistant_mock.py:198-310` 覆盖推荐流、下单流、失败不伪造成功 | PASS |

修复建议：可选统一两个 history 接口的外层形状（recommend 为数组，assistant 为 `{items}`），但这不属于契约违约。

### 1.6 云裳商城下单字段 — PASS

| 检查项 | 证据 | 结论 |
|---|---|---|
| 下单请求模型 | `MallOrderIn {task_token, product_id, size, color, quantity, customer:{name,phone,address}}`，`backend/app/routers/demo_mall.py:30-42` | PASS |
| 前端提交字段 | `mall.js:356-366` 提交同名字段；`product_id` 使用商品 id，`customer` 三字段齐全 | PASS |
| 服务端价格重算 | `order_service.py:145` 使用 `product.price * quantity`，不信任客户端金额 | PASS |
| 平台订单 | `source="agent"`、`external_ref=order_no`、`agent_session_id`，`order_service.py:147-159` | PASS |
| task_token 校验 | `demo_mall.py:95-101` 未找到令牌返回中文 404；`order_service.py:93-110` 校验任务/会话/登录用户 | PASS |
| 响应 | `{order_no,total}` 必需，另含兼容字段 `status/idempotent`，`demo_mall.py:45-49` | PASS（兼容增量） |
| 幂等 | 同一 task 重复提交返回原订单，`order_service.py:98-104, 179-188` | PASS |
| 成功页/选择器 | `checkout.html:60/64/68/74`、`success.html:31`、`index.html:43-44`、`product.html:46/84`、`mall.js:89/95` 均包含契约要求的 `data-testid`/id | PASS |
| 页面路径 | `/demo-mall/`、`product.html?id=`、`checkout.html`、`success.html?order_no=` 均实测 200，`main.py:105` 静态挂载 | PASS |
| 商城 API | `GET /demo-mall/api/products?q=`、`GET /demo-mall/api/products/{id}`、`POST /demo-mall/api/orders` 均存在；商品列表/详情实测 200，下单成功路径由 `test_assistant_mock.py` 的 Mock 浏览器测试覆盖 | PASS |
| 中文错误 | 缺令牌/商品不存在/售罄/尺码颜色不可用均为中文 `detail`，`order_service.py:93-140` | PASS |

修复建议：无。`MallOrderOut` 的两个额外字段属于兼容扩展，建议补写 `CONTRACT_CHANGELOG.md`。

---

## 2. 全量 API 逐项核对

### 2.1 认证（CONTRACTS 3.1）

| 方法 | 路径 | 检查点 | 证据 | 状态 |
|---|---|---|---|---|
| POST | `/api/auth/register` | 路径/方法/请求字段/响应 | `routers/auth.py:57-95`；`schemas.py:20-24, 31-34` | PASS |
| POST | `/api/auth/login` | 路径/方法/请求字段/响应 | `auth.py:98-109`；`schemas.py:26-29` | PASS |
| GET | `/api/auth/me` | Bearer、`UserPublic` | `auth.py:112-115` | PASS |
| POST | `/api/auth/logout` | Bearer、`{ok:true}` | `auth.py:118-125` | PASS |
| — | 错误中文 | 401/409 为中文 | `auth.py:25-26, 72-77, 103-108` | PASS |
| — | 422 参数校验 | 自动校验信息为英文 | `schemas.py:20-34`；无全局处理器（`main.py:49-75`） | **MISMATCH（见 5.1）** |

### 2.2 商品（CONTRACTS 3.2）

| 方法 | 路径 | 检查点 | 证据 | 状态 |
|---|---|---|---|---|
| GET | `/api/products` | `q/category/sort/featured/page/page_size`，`ProductListOut` | `products.py:43-94` | PASS |
| GET | `/api/products/categories` | 路由顺序、`CategoryOut[]` | `products.py:97-110`；运行时 200 | PASS |
| GET | `/api/products/{id}` | `ProductOut`、404 中文 | `products.py:252-257`；实测 404 `商品不存在` | PASS |
| POST | `/api/products/search-by-image` | multipart `file/top_k`、`ImageSearchOut` | `products.py:139-249`；实测 200 | PASS |
| — | 非法 sort | 400 中文 | `products.py:53-54`；实测 400 中文 | PASS |
| — | 缺文件 | 自动 422 英文 | `products.py:141` | **MISMATCH（见 5.1）** |

### 2.3 购物车（CONTRACTS 3.3）

| 方法 | 路径 | 检查点 | 证据 | 状态 |
|---|---|---|---|---|
| GET | `/api/cart` | Bearer、`CartOut` | `cart.py:64-69` | PASS |
| POST | `/api/cart` | `CartAddRequest`、合并同规格 | `cart.py:72-114`；`schemas.py:87-91` | PASS |
| PATCH | `/api/cart/{item_id}` | `{quantity}`、0=删除、`CartOut` | `cart.py:117-138`；`schemas.py:94-95` | PASS |
| DELETE | `/api/cart/{item_id}` | `CartOut` | `cart.py:141-150` | PASS |
| DELETE | `/api/cart` | 空 `CartOut` | `cart.py:153-160` | PASS |
| — | 未登录 | 401 中文 | `cart.py:67`；实测 `请先登录` | PASS |
| — | 错误中文 | 404/400 均为中文 | `cart.py:18-32, 55-61, 91-99` | PASS |

### 2.4 订单（CONTRACTS 3.4）

| 方法 | 路径 | 检查点 | 证据 | 状态 |
|---|---|---|---|---|
| POST | `/api/orders` | `OrderCreateRequest`、默认整车、可传 `item_ids`、模拟支付 `paid`、结算后清空 | `orders.py:38-103`；`schemas.py:125-134` | PASS |
| GET | `/api/orders` | 新到旧 | `orders.py:106-116`（`created_at.desc(), id.desc()`） | PASS |
| GET | `/api/orders/{id}` | 404 中文 | `orders.py:119-126` | PASS |
| POST | `/api/orders/{id}/cancel` | 仅 `paid → cancelled` | `orders.py:129-142` | PASS |
| — | 订单号格式 | `YJ{YYYYMMDDHHMMSS}{4位随机}` | `orders.py:21-28`；测试 `test_assistant_mock.py:268` 断言 18 位 | PASS |
| — | `source` | 平台单 `platform`，商城单 `agent` | `orders.py:90`；`order_service.py:151` | PASS |
| — | 缺 `shipping` | 自动 422 英文 | `schemas.py:125-128` | **MISMATCH（见 5.1）** |

### 2.5 小模型（CONTRACTS 3.5）

| 方法 | 路径 | 检查点 | 证据 | 状态 |
|---|---|---|---|---|
| GET | `/api/small-models/status` | 无 Bearer、`SmallModelsStatus` | `small_models.py:86-93`；实测匿名 200 | PASS |
| POST | `/api/small-models/vision/embed` | multipart `file`、`VisionEmbedResponse` | `small_models.py:97-121`；`schemas.py:169-174` | PASS |
| POST | `/api/small-models/vision/similar` | multipart `file`、`top_k=8`、`VisionSimilarResponse` | `small_models.py:124-182`；`top_k` 为 Query（`:127`） | PASS（位置见 8.2） |
| POST | `/api/small-models/kg/chebyshev` | `{a,b}`、`ChebyshevResponse` | `small_models.py:186-196`；实测 distance=4.0/similarity=0.2 | PASS |
| POST | `/api/small-models/kg/query` | `{text,top_k}`、`KGQueryResponse` | `small_models.py:199-230`；`schemas.py:201-209` | PASS |
| GET | `/api/small-models/kg/graph` | `product_id?`、`limit=60`、`KGGraphOut` | `small_models.py:233-286` | PASS |
| — | 可选 Bearer | 运行时全部可选（`get_optional_user`） | `deps.py:45-49`；`small_models.py:87-93` 等 | PASS（OpenAPI 见 5.4） |
| — | 中文错误 | 图片/维度/服务错误均中文 | `small_models.py:48-71, 81-82, 154-160` | PASS（缺文件 422 见 5.1） |

### 2.6 recommend 接口（CONTRACTS 3.6）

| 方法 | 路径 | 检查点 | 证据 | 状态 |
|---|---|---|---|---|
| POST | `/api/recommend/image` | multipart、SSE、Bearer | `recommend.py:119-147` | PASS |
| GET | `/api/recommend/sessions/{id}` | `{session,messages,result}`、属主校验 | `recommend.py:156-179` | PASS |
| GET | `/api/recommend/history` | 当前用户 stylist 会话 | `recommend.py:182-200` | PASS |
| — | 会话不存在/越权 | 404 中文 | `recommend.py:162-168` | PASS |
| — | 响应结构 OpenAPI | 无 `response_model`，OpenAPI 200 schema 为空 | `recommend.py:156, 182` | **MISSING（见 6.2）** |

### 2.7 recommend SSE 事件逐项

| event | 契约 payload | 实现 | 状态 |
|---|---|---|---|
| `session` | `{session_id, mode, stages}` | `services/recommendation.py:865-872` | PASS |
| `stage` | `{stage,label,progress}` | `recommendation.py:84-85, 901/922/974/983/998` | PASS |
| `vision` | `VisionAnalysis` | `recommendation.py:919`；`schemas.py:242-251` | PASS |
| `candidates` | `{items, metric:"chebyshev", backend}` | `recommendation.py:934-944` | PASS |
| `kg` | `{nodes,edges,metric:"chebyshev",summary}` | `recommendation.py:435-527, 945` | PASS |
| `agent_round` | `{round:1 或 2, label}` | `recommendation.py:975, 984` | PASS |
| `agent_message` | `AgentMessageOut` + `agent_name`；`scores/recipients/message_type` 可见 | `recommendation.py:140-159, 980-981, 992-993`；`schemas.py:300-315` | PASS |
| `revision` | `{agent,product_id,old_score,new_score,reason}` | `recommendation.py:994-995`；`agents/base.py:107-115`（另含 `to_agent`） | PASS（兼容增量） |
| `final` | `RecommendationFinal`（Top3/outfit/advice/kg/mode/elapsed_ms） | `recommendation.py:757-777, 1019`；`schemas.py:274-285` | PASS |
| `warning` | `{code,message,stage}` | `recommendation.py:873-881, 909-916, 931-933, 977/990` | PASS |
| `error` | `{code,message}` | `recommendation.py:1025, 1048-1051` | PASS |
| `done` | `{session_id,elapsed_ms}` | `recommendation.py:1021, 1026-1032, 1052-1058` | PASS |
| 事件 id | 递增 | `recommend.py:91-106` | PASS |
| 固定五智能体 | `fashion/art/aesthetics/price/comfort` 中文名 | `agents/personas.py:23-84` | PASS |
| 两轮与修订 | Round 1 独立、Round 2 具名互评、最多 2 个修订 | `agents/orchestrator.py:106-211`；测试断言 | PASS |

### 2.8 assistant 接口与 SSE（CONTRACTS 3.7）

| 方法/事件 | 检查点 | 证据 | 状态 |
|---|---|---|---|
| POST `/api/assistant/chat` | JSON `{message,session_id?}`、SSE、Bearer | `assistant.py:23-52` | PASS |
| GET `/api/assistant/sessions/{id}` | 会话与步骤 | `assistant.py:63-72`；`services/assistant.py:873-891` | PASS |
| GET `/api/assistant/history` | 当前用户会话 | `assistant.py:55-60` | PASS |
| `session` | `{session_id,kind,mode,engine}` | `services/assistant.py:626-629` | PASS |
| `intent` | `AssistantIntent` | `services/assistant.py:652`；`schemas.py:324-329` | PASS |
| `assistant_message` | `{role,content}` | `services/assistant.py:671-672, 765` | PASS |
| `products` | `{items:[{product,platform_url,mall_url}]}` | `services/assistant.py:221-229, 674-675` | PASS |
| `browse_step` | `{index,action,status,detail,screenshot}` | `services/assistant.py:427-442, 725-733` | PASS |
| `order_created` | `{order_no,source,total}` | `services/assistant.py:752-760`（另含 `session_id`） | PASS（兼容增量） |
| `warning` / `error` | 中文提示，失败不伪造成功 | `services/assistant.py:646-650, 677-699, 767-795` | PASS |
| `done` | `{session_id,elapsed_ms,status}` | `services/assistant.py:814-821` | PASS |
| 响应头/心跳 | SSE 头 + 15s ping | `assistant.py:16-20, 50`；`services/assistant.py:583-588` | PASS |
| OpenAPI 响应结构 | 无 `response_model` | `assistant.py:55, 63` | **MISSING（见 6.2）** |

### 2.9 云裳商城（CONTRACTS 3.8）

| 检查项 | 证据 | 状态 |
|---|---|---|
| 页面 `/demo-mall/`、`product.html?id=`、`checkout.html`、`success.html?order_no=` | `main.py:105`；实测四个 URL 均 200 | PASS |
| `GET /demo-mall/api/products?q=` | `demo_mall.py:58-82`；实测 200 | PASS |
| `GET /demo-mall/api/products/{id}` | `demo_mall.py:85-90`；实测 200；404 为中文 | PASS |
| `POST /demo-mall/api/orders` 入参 | `demo_mall.py:30-42`；`mall.js:356-366` | PASS |
| 服务端重算价格 | `order_service.py:145` | PASS |
| 平台订单 `source=agent`/`external_ref` | `order_service.py:147-159` | PASS |
| 返回 `{order_no,total}` | `demo_mall.py:45-49, 115-120`（另含兼容字段） | PASS |
| 稳定选择器 | `index.html:43-44`、`product.html:46/84`、`checkout.html:60/64/68/74`、`success.html:31`、`mall.js:89/95` | PASS |

---

## 3. 前端 `src/lib/api.ts` 逐项核对（CONTRACTS 6.2）

| 检查项 | 契约 | 实现 | 状态 |
|---|---|---|---|
| 实例方法 | `get/post/patch/delete/upload` | `get/post/patch/del/upload/raw`，`api.ts:211-221`；删除方法名为 `del` | **MISMATCH（见 5.2）** |
| 自动 Bearer | 有 | `api.ts:126-128` | PASS |
| 401 清 token | 有 | `api.ts:87-93, 170-173`；`AppShell.tsx:37-52` 在受保护路径跳登录 | PASS（跳转在外壳实现） |
| 错误转中文 `ApiError` | 有 | `api.ts:8-18, 175-193, 223-234`；422 详情文案取决于后端（见 5.1） | PASS（422 详情见 5.1） |
| `upload` | multipart | `api.ts:218-219`；不手动设置 `Content-Type` | PASS |
| token 存储键 | `yijian_token` / `yijian_user` | `api.ts:4-5`；`writeSession/clearSession` `:55-79` | PASS |
| 超时与取消 | 契约未规定 | `api.ts:136-168`（默认 30s，可取消） | PASS（兼容增强） |
| 响应解析 | JSON/空响应 | `api.ts:196-208` | PASS |

### 3.1 前端调用点核对

| 调用点 | 请求 | 与后端契约 | 状态 |
|---|---|---|---|
| `store/auth.ts:42, 59, 77, 106` | `/auth/login`、`/auth/register`、`/auth/logout`、`/auth/me` | 路径/方法/字段一致 | PASS |
| `pages/Shop.tsx:43, 61` | `/products/categories`、`/products?...` | 路径/查询参数一致 | PASS |
| `pages/ProductDetail.tsx:57, 66` | `/products/{id}`、`/products?category=...` | 路径/查询参数一致 | PASS |
| `pages/Landing.tsx:100, 104` | `/products?featured=true...`、`/products?sort=new...` | 查询参数一致 | PASS |
| `store/cart.ts:33, 48, 65, 77, 89` | `/cart` GET/POST、`/cart/{id}` PATCH/DELETE、`/cart` DELETE | 路径/方法/字段一致 | PASS |
| `pages/Checkout.tsx:83` | `/orders` POST `{shipping,note}` | 与 `OrderCreateRequest` 一致 | PASS |
| `pages/Orders.tsx:34, 52` | `/orders` GET、`/orders/{id}/cancel` POST | 路径/方法一致 | PASS |
| `components/product/ImageSearchDialog.tsx:122` | `/products/search-by-image` multipart | 字段一致（`file/top_k`） | PASS |
| `pages/Assistant.tsx:198-203` | `/assistant/chat` SSE JSON | 路径/字段一致 | PASS |
| `pages/Stylist.tsx:305` | `/recommend/image` SSE FormData | 路径/字段一致 | PASS |
| `lib/useMeta.ts:13` | `/meta` GET | 路径/`Meta` 类型一致 | PASS |

> 说明：前端未调用 `/api/small-models/*` 接口，但这些接口已按契约实现并由后端测试覆盖。

## 4. 前端 `src/lib/sse.ts` 逐项核对（CONTRACTS 6.2/7）

| 检查项 | 契约 | 实现 | 状态 |
|---|---|---|---|
| 函数签名 | `postSSE(url, body 或 FormData, {onEvent,onError,signal})` | `postSSE(path, body, onEvent, {signal,headers})`，`sse.ts:46-51` | **MISMATCH（见 5.3）** |
| `onError` 回调 | 契约列出 | 未提供；错误以异常抛出，由调用方 catch（`Assistant.tsx:204-209`、`Stylist.tsx:308-313`） | **MISMATCH（见 5.3）** |
| URL 前缀 | 契约写 `url` | 自动拼接 `/api`，`sse.ts:68`；调用方传 `/assistant/chat`、`/recommend/image` | PASS（需在契约注明） |
| 自动 Bearer | 有 | `sse.ts:55-57` | PASS |
| 401 处理 | 清 token/失效 | `sse.ts:81-84` | PASS |
| 非 SSE 响应降级 | 契约未写 | `sse.ts:91-95` 读取 JSON 中文 `detail` 并抛 `ApiError` | PASS（兼容增强） |
| 跨 chunk 解析 | 要求 | `sse.ts:99-174`；支持 `\r\n`、`\n`、`\r`、多行 data、注释心跳 | PASS |
| 事件 id | 解析 `id:` | `sse.ts:143-145, 106-127` | PASS |
| 不使用 EventSource | 要求 | 使用 `fetch` + `ReadableStream`，`sse.ts:66-74` | PASS |

---

## 5. MISMATCH 明细与修复建议

### 5.1 MISMATCH-01（中优先级）：422 自动参数校验返回英文

**现象**

FastAPI/Pydantic 的自动请求校验错误没有经过中文转换。实测：

- `POST /api/auth/login`，body `{"username":"a","password":"123"}` → `422`
  `"String should have at least 2 characters"` / `"String should have at least 6 characters"`
- `POST /demo-mall/api/orders`，body `{}` → `422` `"Field required"` × 3
- `POST /api/small-models/vision/similar`，无文件 → `422` `"Field required"`

**契约依据**

- `docs/CONTRACTS.md:48`：“所有业务错误用 `HTTPException(status_code, detail="中文提示")`”。
- 任务硬规则：全中文 UI。
- 前端会把 `detail[].msg` 原样展示：`frontend/src/lib/api.ts:100-105`、`frontend/src/lib/sse.ts:24-29`。

**涉及文件**

- `backend/app/schemas.py:20-34`（`RegisterRequest` / `LoginRequest` 只有长度约束，没有中文错误）
- `backend/app/schemas.py:125-134`（`OrderCreateRequest`）
- `backend/app/routers/demo_mall.py:30-42`（`MallOrderIn` / `MallCustomerIn`）
- `backend/app/routers/products.py:140-143`（`UploadFile = File(...)`）
- `backend/app/routers/small_models.py:97-101, 124-130`（上传文件必填）
- `backend/app/main.py:49-75`（没有 `RequestValidationError` 处理器）

**修复建议（需由共享契约/入口文件的所有者执行）**

1. 在 `main.py`（或新建共享 `app/errors.py`）注册 `RequestValidationError` 异常处理器，将 Pydantic v2 的 `type` + `loc` 映射为中文，例如：
   - `missing` → `缺少必填字段：{字段}`
   - `string_too_short` → `{字段}长度不能少于 N 个字符`
   - `int_parsing` → `{字段}必须是整数`
   - `value_error` → 使用 `ctx.error` 的中文信息
2. 处理器返回统一结构 `{"detail": "中文提示"}`（或继续返回数组，但 `msg` 必须为中文），并在 `api.ts`/`sse.ts` 的现有解析逻辑下可直接展示。
3. 或者为每个 schema 字段增加自定义校验器并抛出中文 `ValueError`；但跨多个 router 时统一异常处理器成本更低。
4. 补测试：至少覆盖登录短密码、demo mall 缺字段、图片缺文件三类。

> 注意：`main.py` 属于共享契约文件，修复前需与 T1/T9 协调，避免与其他并行任务冲突。

### 5.2 MISMATCH-02（低优先级）：`api.delete` 实际为 `api.del`

**现象**

- 契约 `docs/CONTRACTS.md:200`：`api.get/post/patch/delete/upload`。
- 实现 `frontend/src/lib/api.ts:211-221`：只有 `del`，没有 `delete`。
- 现有调用均使用 `api.del`：`frontend/src/store/cart.ts:77, 89`。

**影响**

按契约编写的新代码会得到 TypeScript 编译错误；不是运行时故障，但会造成接口认知漂移。

**修复建议**

- 方案 A（推荐，向后兼容）：在 `api.ts` 增加别名 `delete: ...`，保留 `del`，现有调用不动。
- 方案 B：更新 `docs/CONTRACTS.md`，把 `delete` 改为 `del`，并注明项目统一用 `del`（避免与 JS `delete` 运算符混淆）。
- 两种方案都应同步到 `docs/CONTRACT_CHANGELOG.md`（见 6.1）。

### 5.3 MISMATCH-03（低优先级）：`postSSE` 签名与 `onError` 不一致

**现象**

- 契约 `docs/CONTRACTS.md:201`：`postSSE(url, body|FormData, {onEvent,onError,signal})`。
- 实现 `frontend/src/lib/sse.ts:46-51`：`postSSE(path, body, onEvent, {signal, headers})`。
- 没有 `onError` 回调；错误通过 `throw new ApiError(...)` 抛给调用方。
- 调用方：`Assistant.tsx:198-203`、`Stylist.tsx:305-307`。
- 另外实现会自动拼 `/api`（`sse.ts:68`），契约写的是 `url`。

**影响**

契约与实现不一致；新开发者按契约传 options 对象会把 `onEvent` 传错位置。当前调用方已按实现编写，没有运行时错误。

**修复建议**

- 方案 A（推荐，保持调用方不变）：更新 `CONTRACTS.md` 6.2，写明实际签名：
  `postSSE(pathWithoutApiPrefix, body, onEvent, {signal?, headers?})`，错误通过 reject 抛出。
- 方案 B（兼容旧契约）：在 `sse.ts` 增加重载，支持 `postSSE(url, body, options)`，内部提取 `onEvent/onError/signal`；同时保留现有位置参数形式。
- 无论哪种方案，都应在契约中注明“路径自动加 `/api` 前缀”。

### 5.4 MISMATCH-04（低优先级，仅 OpenAPI 文档）：可选 Bearer 被标注为必填

**现象**

- 契约 `docs/CONTRACTS.md:85`：小模型接口“除 status 外可选 Bearer”。
- 运行时确实允许匿名：所有小模型路由使用 `get_optional_user`（`deps.py:45-49`），实测 `GET /api/small-models/status` 无 token 返回 200。
- 但 `HTTPBearer(auto_error=False)`（`deps.py:12`）仍会让 FastAPI 在 OpenAPI 中生成 `security: [{HTTPBearer: []}]`；`/docs` 显示锁图标，看起来像必填。

**影响**

仅影响 FastAPI `/docs` 和生成客户端的认知；不影响运行时。

**修复建议**

- 在 `CONTRACTS.md` 3.5 加注：“OpenAPI 中 HTTPBearer 为可选认证提示；匿名请求同样合法”。
- 或自定义 `openapi()` 为这些操作追加空 security 备选项 `{}`（OpenAPI 语义表示“可选”），但实现成本高于收益。
- 若后续要生成严格客户端，再考虑处理。

---

## 6. MISSING 明细与修复建议

### 6.1 MISSING-01（低优先级）：缺少 `docs/CONTRACT_CHANGELOG.md`

**契约依据**

`docs/CONTRACTS.md:4`：“需要变更契约时，先写 `docs/CONTRACT_CHANGELOG.md` 并保持向后兼容。”

**现状**

项目中不存在 `docs/CONTRACT_CHANGELOG.md`，但已有以下向后兼容的增量字段/行为：

| 增量 | 位置 | 契约原文 |
|---|---|---|
| `MallOrderOut.status`、`MallOrderOut.idempotent` | `backend/app/routers/demo_mall.py:45-49` | `CONTRACTS.md:137` 只写 `{order_no, total}` |
| `revision.to_agent` | `backend/app/agents/base.py:107-115` | `CONTRACTS.md:113` 列出 5 个字段 |
| `order_created.session_id` | `backend/app/services/assistant.py:752-760` | `CONTRACTS.md:130` 列出 3 个字段 |

这些字段均为“只做加法”的兼容扩展，不破坏现有前端；但没有按契约流程留下变更记录。

**修复建议**

新建 `docs/CONTRACT_CHANGELOG.md`，按时间记录上述增量、原因与兼容性说明；或在下次契约修订时统一补记。不要删除/重命名已有字段。

### 6.2 MISSING-02（低优先级）：recommend/assistant 会话接口缺少 OpenAPI 响应模型

**现状**

以下接口没有 `response_model`，OpenAPI 中 200 响应 schema 为 `{}`：

- `backend/app/routers/recommend.py:156`（`GET /api/recommend/sessions/{id}`）
- `backend/app/routers/recommend.py:182`（`GET /api/recommend/history`）
- `backend/app/routers/assistant.py:55`（`GET /api/assistant/history`）
- `backend/app/routers/assistant.py:63`（`GET /api/assistant/sessions/{id}`）

**契约依据**

- `docs/CONTRACTS.md:99`：`{session: AgentSessionOut, messages: AgentMessageOut[], result}`。
- `docs/CONTRACTS.md:127-128`：“会话与步骤”“当前用户会话”。

**影响**

运行时结构正确（测试已覆盖），但 `/docs` 无法展示响应字段，前后端无法从 OpenAPI 生成类型，契约可验证性降低。

**修复建议**

- 为 recommend 会话详情新增 `RecommendSessionDetail` schema（`session` + `messages` + `result`）。
- 为 assistant 会话详情新增 `AssistantSessionDetail` schema（`session` + `messages` + `browse_task` + `result`）。
- 为两个历史接口加 `response_model=list[AgentSessionOut]`（recommend）与 `list[AgentSessionOut]` 或 `{items:[...]}` 包装模型（assistant）。
- 这些 schema 属于新增，不改现有字段；建议同时写入 `CONTRACT_CHANGELOG.md`。

---

## 7. 中文错误专项

### 7.1 已 PASS 的中文错误

| 场景 | 证据 |
|---|---|
| 未登录（REST） | `deps.py:36-41`；实测 `{"detail":"请先登录"}` |
| 注册重名 | `auth.py:72-77`（409 `该用户名已被注册`） |
| 登录失败 | `auth.py:103-108`（401 `用户名或密码错误`） |
| 商品不存在 | `products.py:254-256`（404 `商品不存在`） |
| 非法排序 | `products.py:53-54`；实测 400 中文 |
| 图片为空/过大 | `products.py:145-149`；`small_models.py:48-56` |
| 购物车商品/规格/库存 | `cart.py:18-32, 55-61, 91-99` |
| 空购物车/库存不足 | `orders.py:53-70` |
| 订单不存在/不可取消 | `orders.py:31-35, 136-139` |
| 小模型向量维度/空向量 | `metrics.py:20-26`；实测 400 中文 |
| 小模型服务降级 | `small_models.py:81-82, 154-160`（502 中文） |
| 商城令牌/商品/规格/库存 | `demo_mall.py:95-101`；`order_service.py:93-140` |
| recommend 流内错误 | `services/recommendation.py:1025, 1050` |
| assistant 流内错误 | `services/assistant.py:785, 794` |
| 前端网络/超时/401/403/404/5xx | `api.ts:162-180, 223-234`；`sse.ts:17-38, 78, 83, 87` |

### 7.2 未 PASS 的中文错误

- 自动 422 校验错误（见 5.1）。
- SPA 兜底对未知 `/api/...` 返回英文 `{"detail":"Not Found"}`（`main.py:112-115`）。这属于路由不存在，不是业务错误；如课程演示要求所有可见文案中文，可顺手改为“接口不存在”。优先级低。

---

## 8. 兼容扩展与观察项（PASS，但有说明）

### 8.1 `budget` 在 OpenAPI 中为 string

- 契约 `CONTRACTS.md:98` 写“budget（可选数字）”。
- 实现 `recommend.py:122` 为 `str | None = Form(...)`，`:41-57` 手动解析为 float；非法值返回中文 400。
- multipart 字段在 HTTP 线上本来就是字符串，运行时行为正确；测试也以字符串 `"3000"` 发送（`tests/test_agents_mock.py:140-147`）。
- 建议：契约注明“multipart 字段以字符串传输，服务端解析为数字”；若希望 OpenAPI 显示 number，可改为 `float | None = Form(...)`，但需同时处理 Pydantic 422 中文（5.1）。

### 8.2 `vision/similar` 的 `top_k` 位置

- 契约 `CONTRACTS.md:90` 只写 `multipart file, top_k=8`，未指定 Form 还是 Query。
- 实现 `small_models.py:124-130` 使用 Query（`top_k` 不在 multipart body）；OpenAPI 已展示为 query 参数。
- 与 `/api/products/search-by-image` 的 Form `top_k` 不一致，但不影响现有调用（前端未使用该接口）。
- 建议在契约中补明位置，或统一两处。

### 8.3 两个 history 接口外层形状不同

- `GET /api/recommend/history` 返回数组（`recommend.py:197-200`）。
- `GET /api/assistant/history` 返回 `{items:[...]}`（`assistant.py:55-60`）。
- 契约只写“列表/当前用户会话”，未规定形状，故 PASS；建议统一，减少前端分支。

### 8.4 `mode` 表示“配置模式”而非“实际生效模式”

- `services/recommendation.py:849` 使用 `configured_mode = "qwen" if qwen_available() else "mock"`；若 Qwen 初始化/调用失败并降级到 Mock，`session` 与 `final.mode` 仍为 `"qwen"`。
- 契约只规定 `mode` 取值 `mock|qwen`，未定义“降级后如何标记”，故 PASS；但对演示 UI 可能造成“显示 Qwen 实际全 Mock”的误解。
- 建议：增加 `effective_mode` 或在降级时把 `mode` 设为 `mock`，并同步前端徽标。

### 8.5 兼容增量字段

| 字段/行为 | 位置 | 说明 |
|---|---|---|
| `MallOrderOut.status` / `idempotent` | `demo_mall.py:45-49` | 兼容增量，不破坏 `{order_no,total}` |
| `revision.to_agent` | `agents/base.py:107-115` | 兼容增量，前端忽略未知字段 |
| `order_created.session_id` | `services/assistant.py:752-760` | 兼容增量，前端只用 `order_no` |
| `done.status`（assistant） | `services/assistant.py:814-821` | 兼容增量 |
| `api.raw` | `frontend/src/lib/api.ts:220` | 客户端扩展 |
| `RequestOptions.timeout` | `frontend/src/lib/api.ts:115-121` | 客户端扩展 |

按 `CONTRACTS.md:4` 的“只做加法扩展”原则，这些均 PASS；但应补 `CONTRACT_CHANGELOG.md`（见 6.1）。

### 8.6 图片大小上限前后端不一致（非契约项）

- 后端图片搜索上限为 8MB：`backend/app/routers/products.py:24`（`MAX_IMAGE_BYTES = 8 * 1024 * 1024`）。
- 前端图片搜索对话框允许 10MB：`frontend/src/components/ImageSearchDialog.tsx:9`（`MAX_BYTES = 10 * 1024 * 1024`），且 413 提示写“10MB 以内”（`:22`）。
- CONTRACTS 未规定图片大小，故不计入契约违约；但用户选择 8–10MB 图片时，前端放行、后端返回 413，提示文案也会误导。建议统一为 8MB（或后端放宽到 10MB），并同步提示。

---

## 9. 审计验证记录

### 9.1 静态/自动化检查

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端全量测试 | `cd backend && .venv/Scripts/python.exe -m pytest -q` | **79 passed**（含 agents/assistant/auth/catalog/small-models/integration） |
| 前端类型检查 | `cd frontend && npm run typecheck` | 通过（`tsc --noEmit` 无输出） |
| OpenAPI 路由清单 | 进程内导出 `app.openapi()["paths"]` | 30 个路径 / 34 个操作（含 `/api/health`、`/api/meta`；契约 32 个操作全部覆盖） |
| products 路由注册顺序 | `app.routers.products.router.routes` | `"" → /categories → /search-by-image → /{product_id}`，顺序正确 |

### 9.2 进程内 HTTP 冒烟（TestClient，未启动长期服务器）

| 请求 | 结果 |
|---|---|
| `GET /api/products/categories` | 200；返回外套/上装/连衣裙/下装/配饰计数 |
| `GET /api/products/999999` | 404 `{"detail":"商品不存在"}` |
| `GET /api/products?sort=bad` | 400 中文排序提示 |
| `PATCH /api/cart/1`（无 token） | 401 `{"detail":"请先登录"}` |
| `POST /api/recommend/image`（无 token） | 401 `{"detail":"请先登录"}` |
| `POST /api/auth/login`（短用户名/密码） | 422（英文 `msg`，见 5.1） |
| `POST /demo-mall/api/orders`（空 body） | 422（英文 `msg`，见 5.1） |
| `GET /api/small-models/status`（无 token） | 200，匿名可访问 |
| `POST /api/small-models/kg/chebyshev` | 200 `distance=4.0, similarity=0.2` |
| 同上，空向量 | 400 中文 |
| `POST /api/small-models/vision/similar`（无文件） | 422（英文 `msg`，见 5.1） |
| `POST /api/products/search-by-image`（样例图，top_k=3） | 200；`items` 3 条，`distance_metric=chebyshev`，`backend=stub` |
| `GET /demo-mall/`、`product.html?id=1`、`checkout.html`、`success.html?order_no=...` | 全部 200，HTML 包含契约要求的 `data-testid`/id |
| `GET /demo-mall/api/products?q=风衣` | 200；返回商品列表 |
| `GET /demo-mall/api/products/1` | 200；返回商品详情 |
| `StreamingResponse` 头模拟 | `content-type: text/event-stream; charset=utf-8`、`cache-control: no-cache, no-transform`、`x-accel-buffering: no` |

### 9.3 未覆盖项

- **真实 Qwen 路径**：当前环境无 `DASHSCOPE_API_KEY`，未验证真实 DashScope 响应对 SSE 字段的映射；Mock 路径与降级逻辑已由测试覆盖。
- **真实 Playwright/Edge 路径**：未启动真实无头浏览器；`BROWSER_ENGINE=mock` 测试验证了同一订单服务与 SSE 事件链。真实浏览器选择器存在性已通过静态 HTML 检查。
- **长期运行服务**：本次未启动 uvicorn/vite 长期进程；全部冒烟使用 TestClient 与静态检查。

---

## 10. 建议后续动作

| 优先级 | 动作 | 责任文件 |
|---|---|---|
| 中 | 增加全局 `RequestValidationError` 中文处理器，并补 422 测试 | `backend/app/main.py` 或共享错误模块；`backend/tests/**` |
| 低 | 增加 `api.delete` 别名或修订契约中的客户端方法名 | `frontend/src/lib/api.ts` / `docs/CONTRACTS.md` |
| 低 | 统一 `postSSE` 契约签名（或在实现中兼容 options 对象） | `docs/CONTRACTS.md` / `frontend/src/lib/sse.ts` |
| 低 | 新建 `docs/CONTRACT_CHANGELOG.md`，记录兼容增量 | `docs/CONTRACT_CHANGELOG.md` |
| 低 | 为 recommend/assistant 会话接口补 `response_model` | `backend/app/schemas.py`、对应 router（需协调共享文件） |
| 可选 | 统一两个 history 接口外层形状；澄清 `budget`/`top_k` 位置；评估 `mode` 的降级语义 | 契约与对应实现 |

> 本审计仅新增 `docs/CONTRACT_AUDIT.md`，未修改任何共享契约或业务代码。
