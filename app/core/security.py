import os
import re
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Any, Union, Optional

from jose import jwt, JWTError
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from app.models.user import User

# 从环境变量加载配置
SECRET_KEY = os.getenv("SECRET_KEY", "a_default_secret_key_if_not_set")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/user/login")

# 使用 pbkdf2_sha256 避免 bcrypt 版本冲突
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    验证密码强度。

    要求：
    - 长度至少8个字符
    - 至少包含一个大写字母
    - 至少包含一个小写字母
    - 至少包含一个数字
    - 至少包含一个特殊字符

    返回: (是否有效, 错误信息)
    """
    if len(password) < 8:
        return False, "密码长度至少为8个字符"

    if not re.search(r"[A-Z]", password):
        return False, "密码必须包含至少一个大写字母"

    if not re.search(r"[a-z]", password):
        return False, "密码必须包含至少一个小写字母"

    if not re.search(r"\d", password):
        return False, "密码必须包含至少一个数字"

    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "密码必须包含至少一个特殊字符 (!@#$%^&*(),.?\":{}|<>)"

    return True, ""


async def revoke_token(token: str) -> None:
    """将token添加到撤销列表（数据库持久化）"""
    from app.models.revoked_token import RevokedToken

    if not token:
        return

    try:
        # 解析token获取过期时间和用户ID
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        exp_timestamp = payload.get("exp")

        if user_id and exp_timestamp:
            expires_at = datetime.fromtimestamp(exp_timestamp)

            # 检查是否已存在（避免重复插入）
            exists = await RevokedToken.filter(token=token).exists()
            if not exists:
                await RevokedToken.create(
                    token=token,
                    user_id=user_id,
                    expires_at=expires_at
                )
    except Exception:
        # 解析失败时仍然记录token（使用默认过期时间）
        try:
            exists = await RevokedToken.filter(token=token).exists()
            if not exists:
                await RevokedToken.create(
                    token=token,
                    user_id="00000000-0000-0000-0000-000000000000",
                    expires_at=datetime.utcnow() + timedelta(days=7)
                )
        except Exception:
            pass


async def is_token_revoked(token: str) -> bool:
    """检查token是否已被撤销"""
    from app.models.revoked_token import RevokedToken

    try:
        return await RevokedToken.filter(token=token).exists()
    except Exception:
        return False


async def cleanup_expired_tokens() -> int:
    """清理已过期的撤销token记录，返回清理数量"""
    from app.models.revoked_token import RevokedToken

    try:
        deleted_count = await RevokedToken.filter(
            expires_at__lt=datetime.utcnow()
        ).delete()
        return deleted_count
    except Exception:
        return 0


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(
    subject: Union[str, Any], expires_delta: timedelta = None
) -> str:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # 检查token是否已被撤销
    if await is_token_revoked(token):
        raise credentials_exception

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = await User.get_or_none(user_id=user_id)
    if user is None:
        raise credentials_exception
    return user
