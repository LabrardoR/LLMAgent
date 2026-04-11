import uuid
from tortoise import fields
from tortoise.models import Model


class MemoryMeta(Model):
    meta_id = fields.UUIDField(pk=True, default=uuid.uuid4)

    memory = fields.ForeignKeyField(
        "models.LongMemory",
        related_name="meta_records",
        unique=True,
        description="关联的长期记忆",
    )

    confidence = fields.FloatField(default=0.8, description="记忆置信度")

    confirmed = fields.BooleanField(default=False, description="是否已被用户确认")

    source = fields.CharField(max_length=30, default="manual", description="manual / regex / llm")

    updated_time = fields.DatetimeField(auto_now=True)

    created_time = fields.DatetimeField(auto_now_add=True)
