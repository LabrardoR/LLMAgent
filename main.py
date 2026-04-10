"""
应用主入口
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent.agent import (
    AVAILABLE_MODELS,
    get_selected_model,
    set_selected_model,
)
from app.api import chat as chat_api
from app.api import knowledge as knowledge_api
from app.api import memory as memory_api
from app.api import tools as tools_api
from app.api import user as user_api
from app.config.db_config import init_db
from app.core.security import cleanup_expired_tokens, get_current_user

load_dotenv()
os.makedirs(os.path.join("app", "static", "avatars"), exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await cleanup_expired_tokens()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(user_api.router, prefix="/api/user", tags=["用户"])
app.include_router(chat_api.router, prefix="/api/chat", tags=["聊天"])
app.include_router(knowledge_api.router, prefix="/api/knowledge", tags=["知识库"])
app.include_router(memory_api.router, prefix="/api/memory", tags=["记忆管理"])
app.include_router(tools_api.router, prefix="/api/tools", tags=["工具管理"])

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ModelSelectRequest(BaseModel):
    model_name: str


@app.get("/api/model/list", summary="获取可用模型列表")
async def list_models():
    return AVAILABLE_MODELS


@app.get("/api/model/current", summary="获取当前生效模型")
async def current_model(current_user=Depends(get_current_user)):
    model_name = await get_selected_model(str(current_user.user_id))
    return {"model_name": model_name}


@app.get("/api/model/stats", summary="获取模型使用统计")
async def model_stats(current_user=Depends(get_current_user)):
    from app.models.chat_run_log import ChatRunLog

    logs = await ChatRunLog.filter(user=current_user).order_by("-created_time").limit(100)
    by_model: dict[str, dict[str, int]] = {}

    for item in logs:
        target = by_model.setdefault(
            item.resolved_model,
            {
                "count": 0,
                "input_chars": 0,
                "output_chars": 0,
                "tool_count": 0,
                "duration_ms": 0,
            },
        )
        target["count"] += 1
        target["input_chars"] += item.input_chars
        target["output_chars"] += item.output_chars
        target["tool_count"] += item.tool_count
        target["duration_ms"] += item.duration_ms

    items = []
    for name, stats in by_model.items():
        count = stats["count"] or 1
        items.append(
            {
                "model_name": name,
                "count": stats["count"],
                "input_chars": stats["input_chars"],
                "output_chars": stats["output_chars"],
                "tool_count": stats["tool_count"],
                "avg_duration_ms": round(stats["duration_ms"] / count, 2),
            }
        )
    return {"items": items}


@app.post("/api/model/select", summary="切换模型")
async def select_model(payload: ModelSelectRequest, current_user=Depends(get_current_user)):
    try:
        await set_selected_model(str(current_user.user_id), payload.model_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="不支持的模型") from exc
    return {"model_name": await get_selected_model(str(current_user.user_id))}


HOST = os.getenv("APP_HOST", "127.0.0.1")
PORT = int(os.getenv("APP_PORT", 8000))


if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True, reload_dirs=["app"])
