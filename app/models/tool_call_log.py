import uuid
from tortoise import fields
from tortoise.models import Model


class ToolCallLog(Model):
    log_id = fields.UUIDField(pk=True, default=uuid.uuid4)

    user = fields.ForeignKeyField("models.User", related_name="tool_logs", description="所属用户")

    conversation = fields.ForeignKeyField(
        "models.Conversation",
        related_name="tool_logs",
        null=True,
        description="所属会话",
    )

    message = fields.ForeignKeyField(
        "models.Message",
        related_name="tool_logs",
        null=True,
        description="来源消息",
    )

    tool_name = fields.CharField(max_length=100, description="工具名称")

    input_text = fields.TextField(default="", description="工具输入")

    output_text = fields.TextField(default="", description="工具输出")

    success = fields.BooleanField(default=True, description="是否成功")

    latency_ms = fields.IntField(default=0, description="耗时毫秒")

    created_time = fields.DatetimeField(auto_now_add=True)
