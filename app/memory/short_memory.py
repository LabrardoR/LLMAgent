"""
短期记忆模块。

用于按会话维度读取最近对话历史，为模型提供多轮上下文。
"""

from datetime import datetime

from app.models.message import Message


async def get_recent_messages(conversation_id: str, limit: int = 10, before_time: datetime = None) -> list[dict]:
    """
    获取会话最近消息，按时间正序返回。

    参数：
    - before_time: 若传入，仅返回该时间点之前的消息，常用于重生成场景。
    """
    query = Message.filter(conversation_id=conversation_id).order_by("-created_time")
    if before_time is not None:
        query = query.filter(created_time__lt=before_time)
    records = await query.limit(limit)
    records = list(reversed(records))
    return [{"role": item.role, "content": item.content} for item in records]
