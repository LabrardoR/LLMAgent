import uuid
from tortoise import fields
from tortoise.models import Model


class Message(Model):

    message_id = fields.UUIDField(pk=True, default=uuid.uuid4)

    conversation = fields.ForeignKeyField("models.Conversation", related_name="messages", description="所属对话")

    user = fields.ForeignKeyField("models.User", related_name="messages", description="所属用户")

    role = fields.CharField(
        max_length=20,
        description="user / assistant / system"
    )

    content = fields.TextField()

    message_type = fields.CharField(
        max_length=20,
        default="short",
        description="short=短期记忆 long=长期记忆"
    )

    tokens = fields.IntField(null=True)

    created_time = fields.DatetimeField(auto_now_add=True)