from fastapi import FastAPI, Depends, HTTPException
import uvicorn
from dotenv import load_dotenv
from app.config.db_config import init_db
from app.api import user as user_api
from app.api import chat as chat_api

from contextlib import asynccontextmanager
import os
from pydantic import BaseModel

from app.core.security import get_current_user
from app.agent.agent import (
    AVAILABLE_MODELS,
    AVAILABLE_TOOLS,
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
    # 应用启动时执行
    await init_db()
    yield
    # 应用关闭时执行 (如果需要)

app = FastAPI(lifespan=lifespan)

from fastapi.staticfiles import StaticFiles

app.include_router(user_api.router, prefix="/api/user", tags=["用户"])
app.include_router(chat_api.router, prefix="/api/chat", tags=["聊天"])
app.mount("/static", StaticFiles(directory=os.path.join("app", "static")), name="static")


class ModelSelectRequest(BaseModel):
    model_name: str


class ToolToggleRequest(BaseModel):
    tool_name: str
    enabled: bool


@app.get("/api/model/list", summary="获取可用模型列表")
async def list_models():
    return AVAILABLE_MODELS


@app.post("/api/model/select", summary="切换模型")
async def select_model(payload: ModelSelectRequest, current_user=Depends(get_current_user)):
    try:
        set_selected_model(str(current_user.user_id), payload.model_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="不支持的模型")
    return {"model_name": get_selected_model(str(current_user.user_id))}


@app.get("/api/tools", summary="获取工具列表")
async def list_tools(current_user=Depends(get_current_user)):
    return AVAILABLE_TOOLS


@app.post("/api/tools/toggle", summary="启用/禁用工具")
async def toggle_tool(payload: ToolToggleRequest, current_user=Depends(get_current_user)):
    try:
        set_tool_enabled(str(current_user.user_id), payload.tool_name, payload.enabled)
    except ValueError:
        raise HTTPException(status_code=400, detail="不支持的工具")
    return {"tool_name": payload.tool_name, "enabled": bool(get_tools_enabled(str(current_user.user_id)).get(payload.tool_name, True))}


HOST = os.getenv("APP_HOST", "127.0.0.1")
PORT = int(os.getenv("APP_PORT", 8000))



if __name__ == '__main__':
    # 添加 reload_dirs 参数，仅监视 app 目录下的代码变更
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, reload_dirs=["app"])
