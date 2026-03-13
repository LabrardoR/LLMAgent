from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    conversation_id: Optional[UUID] = Field(None, description="对话ID，如果是新对话则不传")
    messages: List[ChatMessage]


class ConversationOut(BaseModel):
    conversation_id: UUID
    title: str
    created_time: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationUpdate(BaseModel):
    title: str


class ConversationCreate(BaseModel):
    title: str = Field("新对话", description="会话标题")


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

    model_config = {
        "from_attributes": True
    }
