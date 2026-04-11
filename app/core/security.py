import os
import re
from datetime import datetime, timedelta
from typing import Any, Optional, Union

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.models.user import User

SECRET_KEY = os.getenv("SECRET_KEY", "a_default_secret_key_if_not_set")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/user/login")
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    验证密码强度。

    为了兼顾安全性和易用性，这里只做简单且明确的规则检查。
    """
    if len(password) < 8:
        return False, "密码长度至少为8个字符"
    if not re.search(r"[A-Z]", password):
        return False, "密码必须包含至少一个大写字母"
    if not re.search(r"[a-z]", password):
        return False, "密码必须包含至少一个小写字母"
    if not re.search(r"\d", password):
        return False, "密码必须包含至少一个数字"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=/\\[\]]", password):
        return False, "密码必须包含至少一个特殊字符"
    return True, ""


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode = {"exp": expire, "sub": str(subject)}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def revoke_token(token: str) -> None:
    """将 token 添加到撤销列表。"""
    from app.models.revoked_token import RevokedToken

    if not token:
        return

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        exp_timestamp = payload.get("exp")
        expires_at = datetime.fromtimestamp(exp_timestamp) if exp_timestamp else datetime.utcnow() + timedelta(days=7)
    except Exception:
        user_id = "00000000-0000-0000-0000-000000000000"
        expires_at = datetime.utcnow() + timedelta(days=7)

    exists = await RevokedToken.filter(token=token).exists()
    if not exists:
        await RevokedToken.create(
            token=token,
            user_id=user_id,
            expires_at=expires_at,
        )


async def is_token_revoked(token: str) -> bool:
    from app.models.revoked_token import RevokedToken

    try:
        return await RevokedToken.filter(token=token).exists()
    except Exception:
        return False


async def cleanup_expired_tokens() -> int:
    from app.models.revoked_token import RevokedToken

    try:
        return await RevokedToken.filter(expires_at__lt=datetime.utcnow()).delete()
    except Exception:
        return 0


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if await is_token_revoked(token):
        raise credentials_exception

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    user = await User.get_or_none(user_id=user_id)
    if not user:
        raise credentials_exception
    return user
