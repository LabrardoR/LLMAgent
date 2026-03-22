from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.security import OAuth2PasswordRequestForm
import os
import uuid
from pathlib import Path
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, UserUpdate, PasswordUpdate
from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user,
    oauth2_scheme,
    revoke_token,
    validate_password_strength,
)

router = APIRouter()


@router.post("/register", summary="用户注册")
async def register_user(user_in: UserCreate):
    """
    注册新用户:
    - **account**: 用户账户，必须唯一
    - **password**: 用户密码
    """
    if await User.exists(account=user_in.account):
        raise HTTPException(status_code=400, detail="账户已存在")

    # 验证密码强度
    is_valid, error_msg = validate_password_strength(user_in.password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    hashed_password = get_password_hash(user_in.password)
    user = await User.create(account=user_in.account, password=hashed_password)

    access_token = create_access_token(subject=user.user_id)
    user_out = UserOut.model_validate(user)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_out.dict()
    }


@router.post("/login", summary="用户登录")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await User.get_or_none(account=form_data.username)
    if not user or not verify_password(form_data.password, user.password):
        raise HTTPException(
            status_code=401,
            detail="错误的账户或密码",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(subject=user.user_id)
    user_out = UserOut.model_validate(user)

    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "user": user_out.dict()
    }


@router.get("/me", response_model=UserOut, summary="获取当前用户信息")
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=UserOut, summary="修改当前用户信息")
async def update_user_me(
    user_in: UserUpdate,
    current_user: User = Depends(get_current_user)
):
    user_data = user_in.dict(exclude_unset=True)
    if not user_data:
        raise HTTPException(status_code=400, detail="没有提供要更新的数据")

    await current_user.update_from_dict(user_data)
    await current_user.save()
    return current_user


@router.put("/password", summary="修改密码")
async def update_password(
    payload: PasswordUpdate,
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.old_password, current_user.password):
        raise HTTPException(status_code=400, detail="旧密码不正确")
    if payload.old_password == payload.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")

    # 验证新密码强度
    is_valid, error_msg = validate_password_strength(payload.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    current_user.password = get_password_hash(payload.new_password)
    await current_user.save()
    return {"message": "密码已更新"}


@router.post("/logout", summary="用户登出")
async def logout(token: str = Depends(oauth2_scheme)):
    await revoke_token(token)
    return {"message": "已登出"}


@router.post("/avatar", response_model=UserOut, summary="上传头像")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """
    上传用户头像:
    - **file**: 头像文件（支持 jpg, png 格式）
    """
    # 检查文件类型
    if file.content_type not in ["image/jpeg", "image/png"]:
        raise HTTPException(status_code=400, detail="只支持 jpg 和 png 格式的图片")

    # 获取文件扩展名
    if '.' in file.filename:
        ext = file.filename.split('.')[-1].lower()
    else:
        ext = 'jpg'  # 默认扩展名

    # 生成唯一文件名
    filename = f"{current_user.user_id}.{uuid.uuid4().hex}.{ext}"

    # 确保目录存在
    avatar_dir = Path("app/static/avatars")
    avatar_dir.mkdir(parents=True, exist_ok=True)

    # 保存文件
    file_path = avatar_dir / filename
    with open(file_path, 'wb') as f:
        content = await file.read()
        f.write(content)

    photo_url = f"/static/avatars/{filename}"
    current_user.photo_url = photo_url
    await current_user.save()

    return current_user