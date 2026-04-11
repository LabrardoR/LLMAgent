import uuid
from tortoise import fields
from tortoise.models import Model


class KnowledgeDocumentMeta(Model):
    meta_id = fields.UUIDField(pk=True, default=uuid.uuid4)

    document = fields.ForeignKeyField(
        "models.KnowledgeDocument",
        related_name="meta_records",
        unique=True,
        description="关联文档",
    )

    group_name = fields.CharField(max_length=100, default="", description="文档分组")

    description = fields.TextField(default="", description="文档描述")

    tags = fields.JSONField(default=list, description="标签列表")

    updated_time = fields.DatetimeField(auto_now=True)

    created_time = fields.DatetimeField(auto_now_add=True)
