# 服装知识图谱 · 中文文本嵌入模型

`/graph` 页面的 `semantic_similar` 边由本地中文 NLP 模型 **BGE-small-zh-v1.5（ONNX INT8）** 生成。它把商品的中文名称、副标题、描述、面料、风格、颜色、场景编码为 512 维向量，再用余弦相似度连接语义相近的商品。

## 文件位置

```text
backend/models/nlp/bge-small-zh-v1.5/
├── model_int8.onnx    # 23 MB，ONNX INT8 量化模型
├── tokenizer.json     # 439 KB
└── config.json        # 716 B
```

`backend/models/*` 已被 `.gitignore` 忽略，模型文件不会进入提交记录。

## 下载（国内可访问 hf-mirror）

```bash
cd backend/models/nlp/bge-small-zh-v1.5

curl -L https://hf-mirror.com/Xenova/bge-small-zh-v1.5/resolve/main/onnx/model_int8.onnx \
  -o model_int8.onnx
curl -L https://hf-mirror.com/Xenova/bge-small-zh-v1.5/resolve/main/tokenizer.json \
  -o tokenizer.json
curl -L https://hf-mirror.com/Xenova/bge-small-zh-v1.5/resolve/main/config.json \
  -o config.json
```

## 依赖

```bash
backend/.venv/Scripts/python.exe -m pip install onnxruntime tokenizers
```

`requirements.txt` 已包含这两个依赖。

## 配置

`backend/.env`：

```dotenv
NLP_EMBEDDING_ENABLED=true
NLP_EMBEDDING_MODEL_DIR=models/nlp/bge-small-zh-v1.5
NLP_EMBEDDING_MODEL_FILE=model_int8.onnx
NLP_EMBEDDING_MAX_LENGTH=256
NLP_SEMANTIC_TOP_K=3
NLP_SEMANTIC_THRESHOLD=0.55
```

## 运行方式

- 后端启动预热 `warm_up()` 时加载模型并构建一次图谱；首次建图约 150–300 ms（16 件商品）。
- 每个商品取语义最近的 Top-3 邻居；余弦相似度 ≥ `NLP_SEMANTIC_THRESHOLD` 才连边，避免噪声。
- 语义边与视觉 `similar_to`、搭配 `pairs_with`、词典属性边共存。
- 返回的 `/api/small-models/kg/graph` 中，每条语义边带：

```json
{
  "relation": "semantic_similar",
  "weight": 0.7177,
  "meta": {"method": "text-embedding", "model": "bge-small-zh-v1.5", "similarity": 0.7177}
}
```

- `meta.text_embedding` 提供模型名、维度、后端、加载状态、阈值与语义边数量。
- 模型缺失或 `NLP_EMBEDDING_ENABLED=false` 时，自动跳过语义边，图谱仍保留视觉相似、搭配与属性边，不影响网站启动。

## 为什么不用 PyTorch

ONNX INT8 + `tokenizers` 的安装体积和内存占用远小于 PyTorch，CPU 推理 16 件商品只需几十毫秒，适合本地演示与课堂环境。模型与业务解耦，后续可替换为自训练的中文时尚领域编码器。
