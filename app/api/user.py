from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordRequestForm
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.core.security import get_password_hash, verify_password, create_access_token, get_current_user

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
