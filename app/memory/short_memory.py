"""
短期记忆模块。

用于按会话维度读取最近对话历史，为模型提供多轮上下文。
"""

from datetime import datetime
import logging

from app.models.message import Message

logger = logging.getLogger(__name__)


async def get_recent_messages(conversation_id: str, limit: int = 10, before_time: datetime = None) -> list[dict]: # type: ignore
    """
    获取会话最近消息，按时间正序返回。

    参数：
    - conversation_id: 会话ID
    - limit: 最多返回的消息数量
    - before_time: 若传入，仅返回该时间点之前的消息，常用于重生成场景。

    返回：按时间正序排列的消息列表 [oldest, ..., newest]
    """
    try:
        # 处理时区问题：统一转换为naive datetime
        filter_time = None
        if before_time is not None:
            filter_time = before_time.replace(tzinfo=None) if before_time.tzinfo else before_time

        # 查询消息：按创建时间倒序（最新的在前）
        query = Message.filter(conversation_id=conversation_id).order_by("-created_time")

        if filter_time is not None:
            query = query.filter(created_time__lt=filter_time)

        # 获取最近的 limit 条消息
        records = await query.limit(limit)

        # 反转为正序（最早的在前）
        records = list(reversed(records))

        # 转换为字典格式
        messages = [{"role": item.role, "content": item.content} for item in records]

        logger.info(f"Retrieved {len(messages)} messages for conversation {conversation_id}")
        if messages:
            logger.debug(f"First message role: {messages[0]['role']}, Last message role: {messages[-1]['role']}")

        return messages

    except Exception as e:
        logger.error(f"Error retrieving messages for conversation {conversation_id}: {e}")
        return []


async def get_conversation_summary(conversation_id: str, max_tokens: int = 500) -> str: # type: ignore
    """
    获取会话摘要（可选功能，用于压缩长对话历史）。

    当对话历史过长时，可以使用此函数生成摘要，避免超出token限制。
    """
    # TODO: 实现基于LLM的对话摘要功能
    pass
