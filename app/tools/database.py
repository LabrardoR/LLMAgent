"""
app/tools/database.py
"""

from __future__ import annotations

import re

from langchain.tools import tool

from app.models.message import Message
from app.models.user import User


def _extract_keywords(text: str) -> list[str]:
    items = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9_]+", text.lower())
    return [item for item in items if len(item) > 1][:8]


@tool("database")
async def database_tool(query: str, user_id: str | None = None) -> str:
    """
    查询当前用户最近的聊天历史。

    适合回答“我上次说了什么”“之前提到过某个关键词吗”这类问题。
    """
    if not user_id:
        return "Error: user_id is required to use the database tool."

    user = await User.get_or_none(user_id=user_id)
    if not user:
        return "Error: User not found."

    messages = await Message.filter(user=user, conversation__status=1).order_by("-created_time").limit(30)
    if not messages:
        return "No chat history found."

    keywords = _extract_keywords(query)
    filtered: list[Message] = []
    for item in messages:
        if not keywords:
            filtered.append(item)
            continue
        content = item.content.lower()
        if any(keyword in content for keyword in keywords):
            filtered.append(item)

    if not filtered:
        filtered = list(messages[:10])

    filtered = list(reversed(filtered[:10]))
    lines = []
    for item in filtered:
        lines.append(f"{item.role}: {item.content}")
    return "\n".join(lines)
