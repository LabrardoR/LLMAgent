"""
models/user.py
用户实体类
"""

import uuid
from tortoise import fields
from tortoise.models import Model

class User(Model):
    user_id = fields.UUIDField(pk=True, default=uuid.uuid4, index=True)

    account = fields.CharField(default="", max_length=100, description="账户")
    username = fields.CharField(default="", max_length=100, description="名称")
    password = fields.CharField(default="", max_length=100, description="密码")

    phone = fields.CharField(default="", max_length=100, description="电话号")
    email = fields.CharField(default="", max_length=100)
    gender = fields.SmallIntField(default=0, description="0 为男，1 为女")
    points = fields.BigIntField(default=0, description="积分")
    photo_url = fields.CharField(default="", max_length=100, description="头像的url(地址)")
    
    created_time = fields.DatetimeField(auto_now_add=True)
    updated_time = fields.DatetimeField(auto_now=True)

