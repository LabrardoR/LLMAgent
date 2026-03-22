"""
撤销Token模型
用于持久化已撤销的JWT token
"""

import uuid
from tortoise import fields
from tortoise.models import Model


class RevokedToken(Model):
    id = fields.UUIDField(pk=True, default=uuid.uuid4)

    token = fields.CharField(max_length=500, unique=True, index=True, description="已撤销的token")

    user_id = fields.UUIDField(description="token所属用户ID")

    revoked_at = fields.DatetimeField(auto_now_add=True, description="撤销时间")

    # token过期时间，用于定期清理
    expires_at = fields.DatetimeField(description="token过期时间")
