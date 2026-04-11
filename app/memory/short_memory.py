"""
短期记忆模块。

负责：
1. 读取会话最近历史；
2. 生成会话摘要；
3. 生成默认标题建议。
"""

from __future__ import annotations

from datetime import datetime

from app.models.message import Message


async def get_recent_messages(
    conversation_id: str,
    limit: int = 10,
    before_time: datetime | None = None,
) -> list[dict[str, str]]:
    filter_time = None
    if before_time is not None:
        filter_time = before_time.replace(tzinfo=None) if before_time.tzinfo else before_time

    query = Message.filter(conversation_id=conversation_id).order_by("-created_time")
    if filter_time is not None:
        query = query.filter(created_time__lt=filter_time)

    records = await query.limit(limit)
    records = list(reversed(records))
    return [{"role": item.role, "content": item.content} for item in records]


def suggest_conversation_title(text: str, fallback: str = "新对话") -> str:
    content = " ".join(text.strip().split())
    if not content:
        return fallback
    title = content[:18]
    if len(content) > 18:
        title += "..."
    return title


async def get_conversation_summary(conversation_id: str, max_chars: int = 280) -> str:
    """
    使用简单规则生成摘要。

    这里不强依赖大模型，保证没有外部服务时也能工作。
    """
    messages = await Message.filter(conversation_id=conversation_id).order_by("created_time")
    if not messages:
        return ""

    user_messages = [msg.content.strip() for msg in messages if msg.role == "user" and msg.content.strip()]
    assistant_messages = [msg.content.strip() for msg in messages if msg.role == "assistant" and msg.content.strip()]

    first_user = user_messages[0] if user_messages else ""
    last_user = user_messages[-1] if user_messages else ""
    last_answer = assistant_messages[-1] if assistant_messages else ""

    parts: list[str] = []
    if first_user:
        parts.append(f"用户主要提问：{first_user[:100]}")
    if last_user and last_user != first_user:
        parts.append(f"最近问题：{last_user[:80]}")
    if last_answer:
        parts.append(f"最近回复：{last_answer[:120]}")

    summary = "；".join(parts)
    return summary[:max_chars]
