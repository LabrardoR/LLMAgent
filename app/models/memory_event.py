import uuid
from tortoise import fields
from tortoise.models import Model


class MemoryEvent(Model):
    event_id = fields.UUIDField(pk=True, default=uuid.uuid4)

    user = fields.ForeignKeyField("models.User", related_name="memory_events", description="所属用户")

    memory_type = fields.CharField(max_length=50, description="记忆类型")

    action = fields.CharField(max_length=30, description="created / updated / replaced / deleted / confirmed")

    old_content = fields.TextField(null=True, description="变更前内容")

    new_content = fields.TextField(null=True, description="变更后内容")

    note = fields.CharField(max_length=255, default="", description="补充说明")

    created_time = fields.DatetimeField(auto_now_add=True)
