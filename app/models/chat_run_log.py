import uuid
from tortoise import fields
from tortoise.models import Model


class ChatRunLog(Model):
    run_id = fields.UUIDField(pk=True, default=uuid.uuid4)

    user = fields.ForeignKeyField("models.User", related_name="chat_run_logs", description="所属用户")

    conversation = fields.ForeignKeyField(
        "models.Conversation",
        related_name="chat_run_logs",
        null=True,
        description="所属会话",
    )

    message = fields.ForeignKeyField(
        "models.Message",
        related_name="chat_run_logs",
        null=True,
        description="用户消息",
    )

    selected_model = fields.CharField(max_length=50, description="用户选择的模型")

    resolved_model = fields.CharField(max_length=50, description="实际使用的模型")

    input_chars = fields.IntField(default=0, description="输入字符数")

    output_chars = fields.IntField(default=0, description="输出字符数")

    tool_count = fields.IntField(default=0, description="工具调用次数")

    reference_count = fields.IntField(default=0, description="引用数量")

    duration_ms = fields.IntField(default=0, description="耗时毫秒")

    created_time = fields.DatetimeField(auto_now_add=True)
