"""
models/knowledge_document.py
"""

import uuid
from tortoise import fields
from tortoise.models import Model


class KnowledgeDocument(Model):

    document_id = fields.UUIDField(pk=True, default=uuid.uuid4)

    user = fields.ForeignKeyField("models.User", related_name="documents", description="所属用户")

    title = fields.CharField(max_length=255, description="文档标题")

    file_name = fields.CharField(max_length=255, description="原始文件名")

    file_path = fields.CharField(max_length=500, description="服务器存储路径")

    content = fields.TextField(description="文档全文内容")

    chunk_count = fields.IntField(default=0, description="切分片段数量")

    status = fields.CharField(max_length=30, default="indexed", description="索引状态")

    created_time = fields.DatetimeField(auto_now_add=True)
