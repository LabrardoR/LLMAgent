import uuid
from tortoise import fields
from tortoise.models import Model


class LongMemory(Model):

    memory_id = fields.UUIDField(pk=True, default=uuid.uuid4)

    user = fields.ForeignKeyField("models.User", related_name="long_memories", description="所属用户")

    content = fields.TextField()

    memory_type = fields.CharField(max_length=50, default="profile")

    source_message = fields.ForeignKeyField("models.Message", null=True, related_name="memories", description="来源消息")

    embedding = fields.JSONField(null=True)

    hit_count = fields.IntField(default=0)

    created_time = fields.DatetimeField(auto_now_add=True)
