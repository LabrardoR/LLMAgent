from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    conversation_id: Optional[UUID] = Field(None, description="对话ID，如果是新对话则不传")
    messages: list[ChatMessage]
    group_name: str | None = Field(None, description="限制知识库分组")
    tag: str | None = Field(None, description="限制知识库标签")


class ConversationOut(BaseModel):
    conversation_id: UUID
    title: str
    created_time: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationUpdate(BaseModel):
    title: str


class ConversationCreate(BaseModel):
    title: str = Field("新对话", description="会话标题")


class ConversationBranchRequest(BaseModel):
    message_id: Optional[UUID] = Field(None, description="分支起点消息ID")
    title: str = Field("新的分支会话", description="分支会话标题")


class MessageUpdate(BaseModel):
    content: str = Field(..., description="新的内容")


class RegenerateRequest(BaseModel):
    conversation_id: UUID
    message_id: UUID


class MessageOut(BaseModel):
    message_id: UUID
    role: str
    content: str
    created_time: datetime

    model_config = ConfigDict(from_attributes=True)
