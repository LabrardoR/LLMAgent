"""
记忆相关的 Pydantic Schema
"""

from datetime import datetime

from pydantic import BaseModel, Field


class LongMemoryOut(BaseModel):
    memory_id: str
    memory_type: str
    content: str
    hit_count: int
    confidence: float = Field(0.0, description="记忆置信度")
    confirmed: bool = Field(False, description="是否已确认")
    source: str = Field("manual", description="来源")
    created_time: datetime


class LongMemoryCreate(BaseModel):
    memory_type: str = "custom"
    content: str
    confidence: float = Field(0.95, ge=0.0, le=1.0)


class LongMemoryUpdate(BaseModel):
    content: str
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class LongMemoryConfirmRequest(BaseModel):
    confirmed: bool = True


class MemoryStatsOut(BaseModel):
    total_memories: int
    confirmed_memories: int
    average_confidence: float
    by_type: dict[str, int]
    most_accessed: list[LongMemoryOut]
