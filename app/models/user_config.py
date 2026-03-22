"""
用户配置模型
用于持久化用户的模型选择和工具启用状态
"""

import uuid
from tortoise import fields
from tortoise.models import Model


class UserConfig(Model):
    config_id = fields.UUIDField(pk=True, default=uuid.uuid4)

    user = fields.ForeignKeyField("models.User", related_name="configs", description="所属用户", unique=True)

    selected_model = fields.CharField(max_length=50, default="qwen-turbo", description="选择的模型")

    enabled_tools = fields.JSONField(default=dict, description="工具启用状态 {tool_name: bool}")

    created_time = fields.DatetimeField(auto_now_add=True)

    updated_time = fields.DatetimeField(auto_now=True)