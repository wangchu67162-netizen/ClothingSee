"""Application configuration (env-driven)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "衣见 ATELIER"
    app_version: str = "1.0.0"
    api_prefix: str = "/api"
    debug: bool = True

    # Big models (DashScope OpenAI-compatible)
    llm_mode: str = "auto"  # auto | qwen | mock
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_text_model: str = "qwen-plus"
    qwen_vl_model: str = "qwen3-vl-plus"
    llm_timeout: float = 90.0

    # Small models (owned by the user; only adapters here)
    small_model_mode: str = "stub"  # stub | http
    vision_service_url: str = ""
    nlp_kg_service_url: str = ""
    small_model_timeout: float = 30.0

    # Local Chinese text embedder used to add semantic edges to the fashion KG
    nlp_embedding_enabled: bool = True
    nlp_embedding_model_dir: str = "models/nlp/bge-small-zh-v1.5"
    nlp_embedding_model_file: str = "model_int8.onnx"
    nlp_embedding_max_length: int = 256
    nlp_semantic_top_k: int = 3
    nlp_semantic_threshold: float = 0.55

    # Browser automation
    browser_engine: str = "playwright"  # playwright | browser_use | mock
    browser_headless: bool = True
    playwright_channel: str = "msedge"

    # Optional browser-use engine (install requirements-optional.txt; needs a text LLM key)
    browser_use_model: str = ""  # default: qwen_text_model
    browser_use_max_steps: int = 40
    browser_use_timeout: float = 240.0
    browser_use_executable_path: str = ""  # default: auto-detect Edge/Chrome
    browser_use_fallback_to_playwright: bool = False

    # Auth / runtime
    jwt_secret: str = "dev-change-me-please"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080
    database_url: str = "sqlite:///./data/app.db"
    frontend_dist: str = "../frontend/dist"
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )

    @property
    def llm_enabled(self) -> bool:
        if self.llm_mode == "qwen":
            return True
        if self.llm_mode == "mock":
            return False
        return bool(self.dashscope_api_key.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def database_url_resolved(self) -> str:
        """Resolve sqlite:///./relative URLs against backend/, not the shell cwd."""
        prefix = "sqlite:///./"
        if self.database_url.startswith(prefix):
            path = BACKEND_DIR / self.database_url[len(prefix):]
            return "sqlite:///" + path.as_posix()
        return self.database_url

    @property
    def static_dir(self) -> Path:
        return BASE_DIR / "static"

    @property
    def runtime_dir(self) -> Path:
        return BACKEND_DIR / "runtime"

    @property
    def uploads_dir(self) -> Path:
        return self.runtime_dir / "uploads"

    @property
    def screenshots_dir(self) -> Path:
        return self.runtime_dir / "screenshots"

    @property
    def images_dir(self) -> Path:
        return self.static_dir / "images"

    @property
    def demo_mall_dir(self) -> Path:
        return BASE_DIR / "demo_mall"

    @property
    def frontend_dist_path(self) -> Path:
        path = Path(self.frontend_dist)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        return path.resolve()

    def ensure_dirs(self) -> None:
        for path in (
            BACKEND_DIR / "data",
            self.runtime_dir,
            self.static_dir,
            self.uploads_dir,
            self.screenshots_dir,
            self.images_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
settings.ensure_dirs()
