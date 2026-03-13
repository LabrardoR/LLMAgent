from pydantic import BaseModel, Field
from typing import Optional, Any
from uuid import UUID


class UserCreate(BaseModel):
    account: str = Field(..., description="账户")
    password: str = Field(..., description="密码")


class UserUpdate(BaseModel):
    username: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gender: Optional[int] = None
    photo_url: Optional[str] = None


class PasswordUpdate(BaseModel):
    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., description="新密码")


class UserOut(BaseModel):
    user_id: UUID
    account: str
    username: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    gender: Optional[int]
    points: Optional[int]
    photo_url: Optional[str]

    model_config = {
        "from_attributes": True
    }
