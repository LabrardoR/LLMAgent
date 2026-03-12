from langchain.agents import create_agent
from langchain_community.chat_models import ChatTongyi
from langchain_core.tools import Tool
from app.tools.calculator import calculator_tool
from app.tools.search import search_tool
from app.tools.database import database_tool


def get_agent(user_id: str = None):
    """使用 LangChain 的 ChatTongyi 创建智能助手"""
    
    # 1. 定义工具
    tools = [calculator_tool, search_tool]
    if user_id:
        # 为数据库工具动态创建一个新的 Tool 实例，通过 lambda 传入 user_id
        user_specific_db_tool = Tool(
            name="database_tool",
            func=lambda query: database_tool.func(query, user_id=user_id),
            description=database_tool.description,
            coroutine=lambda query: database_tool.coroutine(query, user_id=user_id)
        )
        tools.append(user_specific_db_tool)

    # 2. 定义大模型
    import os
    dashscope_api_key = os.getenv("DASHSCOPE_API_KEY")
    llm = ChatTongyi(
        model="qwen-turbo",
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
