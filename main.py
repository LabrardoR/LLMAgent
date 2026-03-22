"""
应用主入口
"""

from fastapi import FastAPI, Depends, HTTPException
import uvicorn
from dotenv import load_dotenv
from app.config.db_config import init_db
from app.api import user as user_api
from app.api import chat as chat_api
from app.api import knowledge as knowledge_api

from contextlib import asynccontextmanager
import os
from pydantic import BaseModel
from pathlib import Path
from app.core.security import get_current_user
from app.agent.agent import (
    AVAILABLE_MODELS,
    get_available_tools,
    reload_extension_tools,
    set_selected_model,
    get_selected_model,
    set_tool_enabled,
    get_tools_enabled,
)

# 加载环境变量
load_dotenv()
os.makedirs(os.path.join("app", "static", "avatars"), exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 启动初始化数据库"""
    await init_db()
    yield

app = FastAPI(lifespan=lifespan)

from fastapi.staticfiles import StaticFiles

app.include_router(user_api.router, prefix="/api/user", tags=["用户"])
app.include_router(chat_api.router, prefix="/api/chat", tags=["聊天"])
app.include_router(knowledge_api.router, prefix="/api/knowledge", tags=["知识库"])

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ModelSelectRequest(BaseModel):
    model_name: str


class ToolToggleRequest(BaseModel):
    tool_name: str
    enabled: bool


@app.get("/api/model/list", summary="获取可用模型列表")
async def list_models():
    """获取系统支持的大模型列表。"""
    return AVAILABLE_MODELS


@app.post("/api/model/select", summary="切换模型")
async def select_model(payload: ModelSelectRequest, current_user=Depends(get_current_user)):
    """为当前用户切换默认使用模型。"""
    try:
        await set_selected_model(str(current_user.user_id), payload.model_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="不支持的模型")
    return {"model_name": await get_selected_model(str(current_user.user_id))}


@app.get("/api/tools", summary="获取工具列表")
async def list_tools(current_user=Depends(get_current_user)):
    """获取当前可用工具（含扩展工具）。"""
    return get_available_tools()


@app.post("/api/tools/toggle", summary="启用/禁用工具")
async def toggle_tool(payload: ToolToggleRequest, current_user=Depends(get_current_user)):
    """切换当前用户的工具开关状态。"""
    try:
        await set_tool_enabled(str(current_user.user_id), payload.tool_name, payload.enabled)
    except ValueError:
        raise HTTPException(status_code=400, detail="不支持的工具")
    enabled_tools = await get_tools_enabled(str(current_user.user_id))
    return {"tool_name": payload.tool_name, "enabled": bool(enabled_tools.get(payload.tool_name, True))}


@app.post("/api/tools/reload", summary="重载扩展工具")
async def reload_tools(current_user=Depends(get_current_user)):
    """手动触发扩展工具扫描与重载。"""
    return reload_extension_tools()


HOST = os.getenv("APP_HOST", "127.0.0.1")
PORT = int(os.getenv("APP_PORT", 8000))



if __name__ == '__main__':
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True, reload_dirs=["app"])
