from langchain.agents import create_agent
from langchain_community.chat_models import ChatTongyi
from langchain_core.tools import Tool
from app.tools.calculator import calculator_tool
from app.tools.search import search_tool
from app.tools.database import database_tool


AVAILABLE_MODELS = [
    {"model_name": "qwen-turbo", "provider": "dashscope"},
    {"model_name": "qwen-plus", "provider": "dashscope"},
    {"model_name": "qwen-max", "provider": "dashscope"},
]

AVAILABLE_TOOLS = [
    {"name": "calculator", "description": "数学计算"},
    {"name": "search", "description": "搜索引擎"},
    {"name": "database", "description": "数据库查询"},
]

_selected_model_by_user: dict[str, str] = {}
_enabled_tools_by_user: dict[str, dict[str, bool]] = {}


def get_selected_model(user_id: str) -> str:
    return _selected_model_by_user.get(user_id, "qwen-turbo")


def set_selected_model(user_id: str, model_name: str) -> None:
    allowed = {m["model_name"] for m in AVAILABLE_MODELS}
    if model_name not in allowed:
        raise ValueError("model_not_supported")
    _selected_model_by_user[user_id] = model_name


def get_tools_enabled(user_id: str) -> dict[str, bool]:
    enabled = _enabled_tools_by_user.get(user_id)
    if enabled is None:
        enabled = {"calculator": True, "search": True, "database": True}
        _enabled_tools_by_user[user_id] = enabled
    return enabled


def set_tool_enabled(user_id: str, tool_name: str, enabled: bool) -> None:
    allowed = {t["name"] for t in AVAILABLE_TOOLS}
    if tool_name not in allowed:
        raise ValueError("tool_not_supported")
    current = get_tools_enabled(user_id)
    current[tool_name] = bool(enabled)


def get_agent(user_id: str = None):
    """使用 LangChain 的 ChatTongyi 创建智能助手"""
    tools = []
    enabled = {"calculator": True, "search": True, "database": True}
    model_name = "qwen-turbo"
    if user_id:
        enabled = get_tools_enabled(user_id)
        model_name = get_selected_model(user_id)

    if enabled.get("calculator", True):
        tools.append(calculator_tool)
    if enabled.get("search", True):
        tools.append(search_tool)
    if user_id and enabled.get("database", True):
        user_specific_db_tool = Tool(
            name="database",
            func=lambda query: database_tool.func(query, user_id=user_id),
            description=database_tool.description,
            coroutine=lambda query: database_tool.coroutine(query, user_id=user_id)
        )
        tools.append(user_specific_db_tool)

    # 2. 定义大模型
    import os
    dashscope_api_key = os.getenv("DASHSCOPE_API_KEY")
    llm = ChatTongyi(
        model=model_name,
        dashscope_api_key=dashscope_api_key,
        streaming=True,
    )

    # 3. 创建 Agent
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt="你是一个全能的智能助手，可以使用计算器处理数学题、使用搜索引擎查找实时信息、使用数据库查询用户的聊天历史记录。"
    )

    return agent
