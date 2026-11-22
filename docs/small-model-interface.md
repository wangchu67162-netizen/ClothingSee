# 小模型接口文档（衣见 ATELIER）

> 本文是「视觉小模型 + NLP-KG 小模型」适配层的唯一使用说明。
> 代码目录：`backend/app/small_models/`；HTTP 路由：`backend/app/routers/small_models.py`。
> 本项目**不训练**小模型，只提供可运行的 Stub 基线与接入用户自训练模型的契约。
> Stub 明确标注为 **REPLACEABLE BASELINE**，替换后无需改动业务代码。

---

## 1. 目录与职责

| 文件 | 职责 |
|---|---|
| `backend/app/small_models/base.py` | `VisionModel` / `NLPKGModel` 抽象基类（唯一 Python 契约） |
| `backend/app/small_models/metrics.py` | 切比雪夫距离 / 相似度 |
| `backend/app/small_models/vision_stub.py` | 视觉 Stub：Pillow 提取 256 维确定性向量 |
| `backend/app/small_models/nlp_kg_stub.py` | NLP-KG Stub：中文词典抽取 + 内存知识图谱 |
| `backend/app/small_models/http_adapters.py` | HTTP 适配器：调用远程自训练模型，失败可降级 |
| `backend/app/small_models/factory.py` | 单例工厂、`warm_up()`、embedding 补算、图谱刷新 |
| `backend/app/routers/small_models.py` | 对外 HTTP API（`/api/small-models/*`） |
| `backend/tests/test_small_models.py` | 单元 + 路由测试 |

业务代码（商品检索、五智能体、单智能体）**只能**通过
`from app.small_models.factory import get_vision_model, get_nlp_kg_model, ensure_embeddings`
使用小模型，禁止直接依赖某个具体实现。

---

## 2. Python 契约

```python
# backend/app/small_models/base.py
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

    async def extract(self, text: str) -> dict: ...          # attributes/keywords/triples
    async def rank(self, query_embedding, candidates, top_k) -> list[dict]: ...
    async def neighbors(self, product_id: int, limit: int = 6) -> list[dict]: ...
    async def build_graph(self, products, embeddings) -> dict: ...
    def chebyshev(self, a, b) -> float: ...
    def info(self) -> dict: ...
```

约定：

- `embed` 返回 `dim` 维向量；Stub 输出 L2 归一化（`‖v‖₂ = 1`）。
- `rank` 的入参 `candidates = [{"product_id": int, "embedding": list[float]}]`；
  返回 `[{"product_id", "distance", "similarity"}]`，**按 distance 升序**。
- `extract` 返回：

  ```json
  {
    "attributes": {
      "category": ["上装"],
      "colors": ["月白"],
      "materials": ["真丝"],
      "styles": ["通勤"],
      "occasions": ["约会"],
      "sizes": ["M"]
    },
    "keywords": ["上装", "月白", "真丝", "通勤", "约会", "M"],
    "triples": [{"subject": "查询", "relation": "品类", "object": "上装"}]
  }
  ```

- `build_graph(products, embeddings)` 的 `products` 支持 ORM 对象或 dict；
  `embeddings` 支持 `[{"product_id": 1, "embedding": [...]}]` 或 `{1: [...]}`。
- `info()` 返回至少包含 `name / version / backend / healthy / metric` 的 dict，
  供 `GET /api/small-models/status` 原样输出。

### 2.1 切比雪夫距离与相似度

```text
chebyshev_distance(a, b)   = max_i |a_i - b_i|
chebyshev_similarity(a, b) = 1 / (1 + chebyshev_distance(a, b))
```

- 两个向量必须**非空且等长**，否则抛出 `ValueError`（中文提示），路由转 HTTP 400。
- 相似度落在 `(0, 1]`；完全相同为 `1.0`。
- 例：`a=[1,5]`，`b=[3,2]` → `distance = max(2,3) = 3.0`，`similarity = 1/(1+3) = 0.25`。
- 实现：`backend/app/small_models/metrics.py`；视觉检索、KG 边权、`/kg/chebyshev`
  共用同一实现，不会出现三套算法。

---

## 3. Stub 基线（REPLACEABLE BASELINE）

### 3.1 视觉模型 `vision_stub.py`

| 项目 | 说明 |
|---|---|
| 预处理 | Pillow 打开 → EXIF 转正 → RGB → 缩放到 64×64（LANCZOS） |
| 特征 1 | RGB 直方图：32 bins × 3 通道 = 96 维 |
| 特征 2 | HSV 直方图：32 bins × 3 通道 = 96 维 |
| 特征 3 | 梯度方向直方图：32 bins（0..π，按模长加权）= 32 维 |
| 特征 4 | 2×2 分块颜色矩：每块每通道均值 + 标准差 = 24 维 |
| 特征 5 | 全局统计：明度均值/标准差、饱和度均值/标准差、边缘密度、色彩丰富度、色彩偏移、长宽比 = 8 维 |
| 合计 | **256 维**，末段整体 L2 归一化 |
| 确定性 | 同一图片字节 → 同一向量；无线程/随机数依赖 |
| 模型信息 | `name=yijian-vision-stub`、`version=stub-v1`、`backend=stub`、`dim=256` |

不支持的输入（空字节、损坏文件、非图片）抛出带中文说明的 `ValueError`。

### 3.2 NLP-KG 模型 `nlp_kg_stub.py`

中文词典抽取六个维度：**品类 / 颜色 / 材质 / 风格 / 场景 / 尺码**。

商品知识图谱结构（全部为无向语义，存储为有向边）：

| 关系 `relation` | 方向 | 权重 |
|---|---|---|
| `belongs_to` | 商品 → 品类 | 1.0 |
| `has_color` | 商品 → 颜色 | 1.0 |
| `has_material` | 商品 → 材质 | 1.0 |
| `has_style` | 商品 → 风格 | 1.0 |
| `has_occasion` | 商品 → 场景 | 0.8 |
| `has_size` | 商品 → 尺码 | 0.3 |
| `similar_to` | 商品 ↔ Top-3 切比雪夫近邻（去重、无自环） | `1/(1+distance)` |
| `pairs_with` | 上装 ↔ 下装搭配边（整套推荐用） | 0.5 ~ 0.9（风格/颜色重合度） |

- 节点 id：`product:{商品id}`、`category:{名称}`、`color:{名称}`、
  `material:{名称}`、`style:{名称}`、`occasion:{名称}`、`size:{名称}`。
- `similar_to` 使用视觉 embedding 的 **Top-3 切比雪夫近邻**，对每个商品计算后按
  商品对去重，避免重复边。
- 查询扩展：词典命中 + 同义词/场景扩展（如「上班 → 通勤/商务」）+
  品类互补（上装 → 下装）；再沿 `similar_to` / `pairs_with` 做一跳邻域扩展。
- `query(text, top_k)` 额外返回 `product_ids / scores / related_terms`，
  路由层只暴露契约中的 `triples / products / related_terms`。

---

## 4. HTTP 协议（接入自训练模型，推荐方式）

设置 `SMALL_MODEL_MODE=http` 后，后端通过 `httpx` 调用：

### 4.1 视觉 embedding

```http
POST {VISION_SERVICE_URL}/embed
Content-Type: application/json
Authorization: Bearer <SMALL_MODEL_TOKEN>   # 仅当配置了 token

{
  "images_base64": ["<base64>", "<base64>"],
  "normalize": true
}
```

```json
{
  "embeddings": [[0.01, -0.02, "..."], [0.03, 0.04, "..."]],
  "dim": 256,
  "model_version": "my-vision-v3"
}
```

要求：

- `embeddings` 数量必须等于输入图片数量，向量非空；
- `dim` 必须等于每条向量长度；
- 建议按 `normalize=true` 做 L2 归一化（不强制，但切比雪夫距离对尺度敏感）。

### 4.2 NLP 排序

```http
POST {NLP_KG_SERVICE_URL}/rank
Content-Type: application/json

{
  "query_embedding": [0.1, 0.2, "..."],
  "text": "通勤真丝衬衫",
  "candidates": [
    {"product_id": 1, "embedding": [0.11, 0.19, "..."]},
    {"product_id": 2, "embedding": [0.30, 0.01, "..."]}
  ],
  "top_k": 8
}
```

```json
{
  "matches": [
    {"product_id": 1, "distance": 0.12, "similarity": 0.892857},
    {"product_id": 2, "distance": 0.31, "similarity": 0.763359}
  ],
  "extracted": {"attributes": {"category": ["上装"]}}
}
```

后端会按 `distance` 升序二次排序（防御远程服务顺序不一致），并截断到 `top_k`。

### 4.3 属性抽取

```http
POST {NLP_KG_SERVICE_URL}/extract
Content-Type: application/json

{"text": "想找一件通勤的黑色真丝衬衫，M码"}
```

```json
{
  "attributes": {
    "category": ["上装"],
    "colors": ["黑"],
    "materials": ["真丝"],
    "styles": ["通勤"],
    "occasions": [],
    "sizes": ["M"]
  },
  "keywords": ["上装", "黑", "真丝", "通勤", "M"],
  "triples": [{"subject": "查询", "relation": "品类", "object": "上装"}]
}
```

> HTTP 协议只定义 `embed / rank / extract` 三个远程接口。
> `build_graph / neighbors / chebyshev / query 的图运算` 在后端本地完成
> （HTTP 适配器内部复用 `NLPKGStub` 的图结构），不额外发请求。

### 4.4 超时、鉴权与错误

- 超时：`SMALL_MODEL_TIMEOUT`（默认 30 秒），作用于每次请求。
- 鉴权：配置 `SMALL_MODEL_TOKEN` 时自动附加 `Authorization: Bearer <token>`；
  日志与响应中**不会**输出 token。
- 失败判定：连接失败、超时、HTTP ≥ 400、响应不是合法 JSON、字段缺失/维度不一致。
- 降级：`SMALL_MODEL_FALLBACK_TO_STUB=true`（默认）时记录 warning 并自动使用 Stub，
  API 仍返回 200（`status` 中 `degraded=true`、`last_error` 可见）；
  设为 `false` 时返回 HTTP 502 与中文提示「小模型服务暂不可用」。

---

## 5. 环境变量

配置写在 `backend/.env` 或进程环境变量中。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SMALL_MODEL_MODE` | `stub` | `stub`（本地基线）或 `http`（远程自训练模型） |
| `VISION_SERVICE_URL` | 空 | 远程视觉服务根地址，例如 `http://127.0.0.1:9001` |
| `NLP_KG_SERVICE_URL` | 空 | 远程 NLP-KG 服务根地址，例如 `http://127.0.0.1:9002` |
| `SMALL_MODEL_TIMEOUT` | `30` | 单次请求超时（秒） |
| `SMALL_MODEL_TOKEN` | 空 | 可选 Bearer token；不会写日志 |
| `SMALL_MODEL_FALLBACK_TO_STUB` | `true` | 远程失败是否自动降级到 Stub |

> `SMALL_MODEL_TOKEN` / `SMALL_MODEL_FALLBACK_TO_STUB` 由
> `http_adapters.py` 从环境变量或 `backend/.env` 读取（不进入共享 `Settings`，
> 避免改动共享契约文件 `config.py`）。

切换模式后需重启后端（工厂单例在启动时创建）。

---

## 6. 启动预热与 embedding 表

`backend/app/main.py` 的 lifespan 会在种子数据就绪后调用
`small_models.factory.warm_up()`（通过 `run_in_threadpool`，因此内部可安全
`asyncio.run`）：

1. `init_db()` 确保表存在；
2. 读取全部商品，补算缺失 / 维度不一致 / 版本不一致的 embedding；
3. 写入 `embeddings` 表（`product_id / vector / dim / model_version / updated_at`）；
4. 用 embedding 构建内存知识图谱（Top-3 `similar_to`、属性边、`pairs_with`）；
5. 空库不报错，图谱为空，状态接口仍可用。

向量来源：

- 有商品图：`/static/images/products/*.webp` 读取字节后编码；
- 图片缺失或损坏：使用 `text_fallback_embedding()`（sku/名称/品类/颜色/面料
  sha256 派生的确定性 256 维向量），保证图谱完整，并记录 warning。

其他模块（如 T2 种子）可选用：

```python
from app.small_models.factory import ensure_embeddings

summary = ensure_embeddings(db)          # 增量补算
summary = ensure_embeddings(db, force=True)  # 全量重算（换模型/改维度后）
```

HTTP 模式下视觉模型版本带每次启动的随机后缀，因此**每次启动都会重新校验并
补算一次 embedding**，用于感知远程模型版本/维度变化；Stub 模式则复用缓存。

---

## 7. 维度变化后重建 embedding

切比雪夫距离要求向量等长。更换模型或修改输出维度后，必须重建全部 embedding，
否则新旧向量无法比较。

方式一（推荐，自动）：修改模型后重启后端。`warm_up()` 检测到
`row.dim != vision.dim` 或 `row.model_version != vision.version` 会自动重算；
HTTP 模式每次启动都会重新校验。

方式二（手动强制）：

```python
# backend/ 目录下
from app.database import SessionLocal
from app.small_models.factory import ensure_embeddings, warm_up

with SessionLocal() as db:
    ensure_embeddings(db, force=True)
warm_up()
```

方式三（清空后重建）：

```sql
DELETE FROM embeddings;
```

然后重启后端或调用 `warm_up()`。前端无需改动；`/api/small-models/status`
会显示最新的 `dim` 与 `model_version`。

---

## 8. 本项目对外 HTTP API

基础路径 `/api/small-models`，除 `status` 外均为可选 Bearer（匿名可演示）。
所有错误返回中文 `detail`。

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| GET | `/status` | — | `SmallModelsStatus` |
| POST | `/vision/embed` | multipart `file` | `VisionEmbedResponse` |
| POST | `/vision/similar` | multipart `file` + `top_k=8`（query 或 form 均可，form 优先） | `VisionSimilarResponse` |
| POST | `/kg/chebyshev` | `{a:[...],b:[...]}` | `ChebyshevResponse` |
| POST | `/kg/query` | `{text,top_k}` | `KGQueryResponse` |
| GET | `/kg/graph` | `product_id?,limit=60` | `KGGraphOut` |

```bash
# 状态（stub 模式 dim=256）
curl http://127.0.0.1:8000/api/small-models/status

# 图片向量化
curl -F "file=@sample.webp" http://127.0.0.1:8000/api/small-models/vision/embed

# 以图搜衣
curl -F "file=@sample.webp" "http://127.0.0.1:8000/api/small-models/vision/similar?top_k=8"

# 切比雪夫：distance=3.0, similarity=0.25
curl -X POST http://127.0.0.1:8000/api/small-models/kg/chebyshev \
  -H "Content-Type: application/json" \
  -d '{"a":[1,5],"b":[3,2]}'

# 中文查询 + 图谱扩展
curl -X POST http://127.0.0.1:8000/api/small-models/kg/query \
  -H "Content-Type: application/json" \
  -d '{"text":"通勤真丝衬衫","top_k":6}'

# 图谱快照（可聚焦某商品）
curl "http://127.0.0.1:8000/api/small-models/kg/graph?limit=60"
```

上传校验：必须是 Pillow 可识别的图片，大小 **≤ 8MB**，否则返回 400 中文提示。
`/vision/similar` 会自动补算缺失 embedding；数据库为空时返回空 `matches`，不报错。

---

## 9. 替换为自训练模型

### 方式 A：本地实现（同进程）

1. 在 `backend/app/small_models/` 新建 `vision_local.py` / `nlp_kg_local.py`，
   继承 `VisionModel` / `NLPKGModel` 并实现全部抽象方法；
2. 权重放在 `backend/models/`（不要提交大文件，加入 `.gitignore`）；
3. 在 `factory.py` 的 `get_vision_model()` / `get_nlp_kg_model()` 中注册
   `local` 分支（或把 `SMALL_MODEL_MODE` 扩展为 `local`）；
4. 确保 `info()` 返回真实 `version` 与 `dim`；
5. 重启后端，`warm_up()` 自动重建 embedding。

### 方式 B：HTTP 服务（推荐，训练与业务解耦）

1. 用任意框架（FastAPI/Flask/TorchServe 等）实现三个接口：
   `POST /embed`、`POST /rank`、`POST /extract`，JSON 见第 4 节；
2. 启动服务，例如 `http://127.0.0.1:9001` 与 `http://127.0.0.1:9002`；
3. 修改 `backend/.env`：

   ```dotenv
   SMALL_MODEL_MODE=http
   VISION_SERVICE_URL=http://127.0.0.1:9001
   NLP_KG_SERVICE_URL=http://127.0.0.1:9002
   SMALL_MODEL_TIMEOUT=30
   SMALL_MODEL_TOKEN=
   SMALL_MODEL_FALLBACK_TO_STUB=true
   ```

4. 重启后端；访问 `/api/small-models/status` 确认 `backend=http`、`healthy=true`、
   `dim/model_version` 正确；
5. 若维度变化，按第 7 节重建 embedding。

业务代码无需任何修改：五智能体与单智能体只通过 `factory` 获取模型。

---

## 10. 测试

```bash
cd "C:/Users/cc/Desktop/服装平台项目/backend"
.venv/Scripts/python.exe -m pytest tests/test_small_models.py -q
```

覆盖内容：

- 切比雪夫已知值 `[1,5] vs [3,2] == 3.0`、非法向量；
- embedding 256 维、L2 归一化、确定性、批量一致性、坏图报错；
- `rank` 按距离升序；
- KG 建图包含 `similar_to` / 属性边 / `pairs_with`，查询扩展命中；
- `warm_up()` 写入 embeddings、重复调用走缓存、空库不报错；
- 路由：status、embed、similar 排序、chebyshev、kg/query、kg/graph、
  8MB 与坏图校验。

所有测试使用临时 SQLite 与现场生成的 Pillow 图片，不需要网络、API Key 或
真实商品数据。
