"""FastAPI 应用入口：API 路由 + 静态前端托管。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .routers import assets, chat, research


def create_app() -> FastAPI:
    app = FastAPI(title="AI 投研助手 MVP", version="0.1.0")
    init_db()
    # 先注册 API 路由，再托管前端静态文件，保证 /api 优先匹配。
    app.include_router(assets.router)
    app.include_router(research.router)
    app.include_router(chat.router)

    frontend = settings.frontend_dir
    if frontend.exists():
        app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")

    return app


app = create_app()
