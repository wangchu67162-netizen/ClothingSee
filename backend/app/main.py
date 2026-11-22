"""FastAPI entry point. Router implementations are owned by parallel workstreams."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .config import settings
from .database import SessionLocal, init_db
from .schemas import MetaOut

logger = logging.getLogger("yijian")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        from .seed import seed_if_empty

        with SessionLocal() as db:
            await run_in_threadpool(seed_if_empty, db)
    except Exception:  # pragma: no cover - seed is written by another workstream
        logger.exception("Seed failed; continuing with an empty database")

    try:
        from .small_models.factory import warm_up

        await run_in_threadpool(warm_up)
    except Exception:
        logger.warning("Small-model warm-up skipped (adapter not ready yet)")

    yield

    try:
        from .browser.playwright_driver import shutdown_browser

        await shutdown_browser()
    except Exception:
        pass


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI 服装买手店：电商基础能力 + 浏览器购物智能体 + 五智能体穿搭评议 + 小模型适配层",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _include_routers() -> None:
    from .routers import assistant, auth, cart, demo_mall, orders, products, recommend, small_models

    modules = [auth, products, cart, orders, small_models, recommend, assistant]
    for module in modules:
        app.include_router(module.router, prefix=settings.api_prefix)
    # Demo mall API keeps its own /demo-mall/api path (no /api prefix).
    app.include_router(demo_mall.router)


_include_routers()


@app.get("/api/health", tags=["系统"])
def health() -> dict:
    return {"status": "ok", "version": settings.app_version}


@app.get("/api/meta", response_model=MetaOut, tags=["系统"])
def meta() -> MetaOut:
    mode = "qwen" if settings.llm_enabled else "mock"
    return MetaOut(
        app_name=settings.app_name,
        version=settings.app_version,
        mode=mode,
        llm_mode=settings.llm_mode,
        small_model_mode=settings.small_model_mode,
        features={
            "qwen": settings.llm_enabled,
            "browser_automation": True,
            "multi_agent": True,
            "small_model_http": settings.small_model_mode == "http",
        },
    )


# Static/runtime mounts. Registered before the SPA catch-all.
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
app.mount("/screenshots", StaticFiles(directory=str(settings.screenshots_dir)), name="screenshots")
app.mount("/uploads", StaticFiles(directory=str(settings.uploads_dir)), name="uploads")
app.mount("/demo-mall", StaticFiles(directory=str(settings.demo_mall_dir), html=True), name="demo-mall")

_frontend_dist = settings.frontend_dist_path
if _frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="frontend-assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path.startswith(("api/", "docs", "openapi.json", "redoc")):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    index = _frontend_dist / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        status_code=200,
        content={
            "app": settings.app_name,
            "message": "后端已启动。开发模式请访问 http://127.0.0.1:5173 ；或先构建前端。",
            "docs": "/docs",
        },
    )
