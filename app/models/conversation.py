"""
Conversation实体类
一个对话对应多条Message
"""
import uuid
from tortoise import fields
from tortoise.models import Model


class Conversation(Model):

    conversation_id = fields.UUIDField(pk=True, default=uuid.uuid4)

    user = fields.ForeignKeyField("models.User", related_name="conversations", description="所属用户")

    title = fields.CharField(max_length=255, default="新对话")

    status = fields.SmallIntField(default=1, description="1=正常 0=删除")

    created_time = fields.DatetimeField(auto_now_add=True)

    updated_time = fields.DatetimeField(auto_now=True)