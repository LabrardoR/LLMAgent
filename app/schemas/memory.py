"""
记忆相关的 Pydantic Schema
"""

from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class LongMemoryOut(BaseModel):
    """长期记忆输出模型"""
    memory_id: str
    memory_type: str
    content: str
    hit_count: int
    created_time: datetime

    class Config:
        from_attributes = True


class LongMemoryCreate(BaseModel):
    """手动创建长期记忆"""
    memory_type: str = "custom"
    content: str


class LongMemoryUpdate(BaseModel):
    """更新长期记忆"""
    content: str


class MemoryStatsOut(BaseModel):
    """记忆统计信息"""
    total_memories: int
    by_type: dict[str, int]
    most_accessed: list[LongMemoryOut]
