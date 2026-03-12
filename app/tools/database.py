from langchain.tools import tool
from app.models.message import Message


@tool
async def database_tool(query: str, user_id: str = None) -> str:
    """
    一个数据库工具，可以用来查询当前用户的聊天历史记录。
    当用户问'我上次说了什么'或类似问题时，使用此工具。
    """
    if not user_id:
        return "Error: user_id is required to use the database tool."

    messages = await Message.filter(user_id=user_id).order_by("-created_time").limit(10)

    if not messages:
        return "No chat history found."

    result = []
    for msg in reversed(messages):
        result.append(f"{msg.role}: {msg.content}")

    return "\n".join(result)
