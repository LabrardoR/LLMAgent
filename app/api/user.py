from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.security import OAuth2PasswordRequestForm

from app.core.security import (
    create_access_token,
    get_current_user,
    get_password_hash,
    oauth2_scheme,
    revoke_token,
    validate_password_strength,
    verify_password,
)
from app.core.storage import AVATAR_ROOT, build_asset_url, make_unique_filename, safe_unlink, user_avatar_dir
from app.models.user import User
from app.schemas.user import PasswordUpdate, UserCreate, UserOut, UserUpdate

router = APIRouter()


@router.post("/register", summary="用户注册")
async def register_user(user_in: UserCreate):
    if await User.exists(account=user_in.account):
        raise HTTPException(status_code=400, detail="账户已存在")

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
        "user": user_out.model_dump(),
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
        "user": user_out.model_dump(),
    }


@router.get("/me", response_model=UserOut, summary="获取当前用户信息")
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=UserOut, summary="修改当前用户信息")
async def update_user_me(
    user_in: UserUpdate,
    current_user: User = Depends(get_current_user),
):
    user_data = user_in.model_dump(exclude_unset=True)
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
    current_user: User = Depends(get_current_user),
):
    allowed_types = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="只支持 jpg/png/webp 格式的图片")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件不能为空")
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="头像文件不能超过 5MB")

    avatar_dir = user_avatar_dir(str(current_user.user_id))
    file_name = file.filename or f"avatar{allowed_types[file.content_type]}"
    filename = make_unique_filename(file_name, fallback_ext=allowed_types[file.content_type])
    file_path = avatar_dir / filename
    with open(file_path, "wb") as f:
        f.write(content)

    if current_user.photo_url:
        parts = [item for item in current_user.photo_url.split("/") if item]
        if len(parts) >= 3 and parts[0] in {"assets", "static"} and parts[1] == "avatars":
            old_path = AVATAR_ROOT.joinpath(*parts[2:])
            safe_unlink(old_path, root=AVATAR_ROOT)

    current_user.photo_url = build_asset_url("avatars", str(current_user.user_id), filename)
    await current_user.save()
    return current_user
