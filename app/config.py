"""应用配置：从仓库根目录 .env 与环境变量读取，环境变量优先。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """极简 .env 解析：不覆盖已存在的环境变量。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split("#", 1)[0].strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv(ROOT_DIR / ".env")


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL"))
    openai_base_url: str | None = field(default_factory=lambda: _env("OPENAI_BASE_URL") or None)
    app_host: str = field(default_factory=lambda: _env("APP_HOST", "127.0.0.1"))
    app_port: int = field(default_factory=lambda: _env_int("APP_PORT", 8000))
    database_path: str = field(default_factory=lambda: _env("DATABASE_PATH", "data/assistant.db"))
    request_timeout_seconds: float = field(
        default_factory=lambda: _env_float("REQUEST_TIMEOUT_SECONDS", 12.0)
    )
    ai_timeout_seconds: float = field(
        default_factory=lambda: _env_float("AI_TIMEOUT_SECONDS", 90.0)
    )

    @property
    def db_file(self) -> Path:
        path = Path(self.database_path)
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path

    @property
    def data_dir(self) -> Path:
        return self.db_file.parent

    @property
    def frontend_dir(self) -> Path:
        return ROOT_DIR / "frontend"

    @property
    def prompt_path(self) -> Path:
        return ROOT_DIR / "prompts" / "grounded_analysis.md"

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
