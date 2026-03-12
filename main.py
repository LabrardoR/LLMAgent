from fastapi import FastAPI
import uvicorn
from dotenv import load_dotenv
from app.config.db_config import init_db
from app.api import user as user_api
from app.api import chat as chat_api

from contextlib import asynccontextmanager

# 加载环境变量
load_dotenv()


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

# 挂载静态文件目录
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")


if __name__ == '__main__':
    # 添加 reload_dirs 参数，仅监视 app 目录下的代码变更
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, reload_dirs=["app"])