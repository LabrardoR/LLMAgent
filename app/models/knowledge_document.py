"""
models/KnowledgeDocument.py
"""

import uuid
from tortoise import fields
from tortoise.models import Model


class KnowledgeDocument(Model):

    document_id = fields.UUIDField(pk=True, default=uuid.uuid4)

    user = fields.ForeignKeyField("models.User", related_name="documents", description="所属用户")

    title = fields.CharField(max_length=255)

    content = fields.TextField()

    embedding = fields.JSONField(null=True)

    source = fields.CharField(max_length=255, null=True)

    created_time = fields.DatetimeField(auto_now_add=True)