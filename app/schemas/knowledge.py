from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class KnowledgeDocumentOut(BaseModel):
    document_id: UUID
    title: str
    file_name: str
    chunk_count: int
    status: str
    group_name: str = ""
    tags: list[str] = []
    description: str = ""
    created_time: datetime


class KnowledgeSearchItem(BaseModel):
    document_id: str
    title: str
    chunk_index: int
    score: float
    snippet: str
    content: str
    group_name: str = ""
    tags: list[str] = []


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(4, ge=1, le=10)
    group_name: str | None = None
    tag: str | None = None
