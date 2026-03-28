"""
记忆管理 API。

提供长期记忆的查看、创建、修改、删除功能。
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import List

from app.schemas.memory import (
    LongMemoryOut,
    LongMemoryCreate,
    LongMemoryUpdate,
    MemoryStatsOut,
)
from app.models.user import User
from app.models.long_memory import LongMemory
from app.core.security import get_current_user
from app.rag.vector_store import get_embeddings_model

router = APIRouter()


@router.get("/long-memories", response_model=List[LongMemoryOut], summary="获取所有长期记忆")
async def get_long_memories(
    memory_type: str = None,
    current_user: User = Depends(get_current_user)
):
    """
    获取当前用户的所有长期记忆。

    可选参数：
    - memory_type: 筛选特定类型的记忆（name, city, job, hobby, age, custom等）
    """
    query = LongMemory.filter(user_id=str(current_user.user_id))

    if memory_type:
        query = query.filter(memory_type=memory_type)

    memories = await query.order_by("-created_time")

    return [
        LongMemoryOut(
            memory_id=str(mem.memory_id),
            memory_type=mem.memory_type,
            content=mem.content,
            hit_count=mem.hit_count,
            created_time=mem.created_time,
        )
        for mem in memories
    ]


@router.get("/long-memories/stats", response_model=MemoryStatsOut, summary="获取记忆统计信息")
async def get_memory_stats(current_user: User = Depends(get_current_user)):
    """获取当前用户的记忆统计信息"""
    user_id = str(current_user.user_id)
    memories = await LongMemory.filter(user_id=user_id).all()

    # 按类型统计
    by_type = {}
    for mem in memories:
        by_type[mem.memory_type] = by_type.get(mem.memory_type, 0) + 1

    # 最常访问的记忆（top 5）
    most_accessed = sorted(memories, key=lambda m: m.hit_count, reverse=True)[:5]

    return MemoryStatsOut(
        total_memories=len(memories),
        by_type=by_type,
        most_accessed=[
            LongMemoryOut(
                memory_id=str(mem.memory_id),
                memory_type=mem.memory_type,
                content=mem.content,
                hit_count=mem.hit_count,
                created_time=mem.created_time,
            )
            for mem in most_accessed
        ],
    )


@router.post("/long-memories", response_model=LongMemoryOut, summary="手动创建长期记忆")
async def create_long_memory(
    payload: LongMemoryCreate,
    current_user: User = Depends(get_current_user)
):
    """
    手动创建一条长期记忆。

    用于用户主动添加重要信息，而不是由系统自动提取。
    """
    user_id = str(current_user.user_id)

    # 检查是否已存在相同内容
    exists = await LongMemory.filter(
        user_id=user_id,
        memory_type=payload.memory_type,
        content=payload.content
    ).exists()

    if exists:
        raise HTTPException(status_code=400, detail="该记忆已存在")

    # 生成embedding
    try:
        embeddings_model = get_embeddings_model()
        embedding = embeddings_model.embed_query(payload.content)
    except Exception as e:
        print(f"Failed to generate embedding: {e}")
        embedding = None

    # 创建记忆
    memory = await LongMemory.create(
        user_id=user_id,
        memory_type=payload.memory_type,
        content=payload.content,
        embedding=embedding,
    )

    return LongMemoryOut(
        memory_id=str(memory.memory_id),
        memory_type=memory.memory_type,
        content=memory.content,
        hit_count=memory.hit_count,
        created_time=memory.created_time,
    )


@router.put("/long-memories/{memory_id}", response_model=LongMemoryOut, summary="更新长期记忆")
async def update_long_memory(
    memory_id: str,
    payload: LongMemoryUpdate,
    current_user: User = Depends(get_current_user)
):
    """更新指定的长期记忆内容"""
    memory = await LongMemory.get_or_none(
        memory_id=memory_id,
        user_id=str(current_user.user_id)
    )

    if not memory:
        raise HTTPException(status_code=404, detail="记忆不存在")

    # 更新内容
    memory.content = payload.content

    # 重新生成embedding
    try:
        embeddings_model = get_embeddings_model()
        memory.embedding = embeddings_model.embed_query(payload.content)
    except Exception as e:
        print(f"Failed to generate embedding: {e}")

    await memory.save()

    return LongMemoryOut(
        memory_id=str(memory.memory_id),
        memory_type=memory.memory_type,
        content=memory.content,
        hit_count=memory.hit_count,
        created_time=memory.created_time,
    )


@router.delete("/long-memories/{memory_id}", summary="删除长期记忆")
async def delete_long_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user)
):
    """删除指定的长期记忆"""
    memory = await LongMemory.get_or_none(
        memory_id=memory_id,
        user_id=str(current_user.user_id)
    )

    if not memory:
        raise HTTPException(status_code=404, detail="记忆不存在")

    await memory.delete()
    return {"message": "记忆已删除"}


@router.delete("/long-memories", summary="清空所有长期记忆")
async def clear_long_memories(
    memory_type: str = None,
    current_user: User = Depends(get_current_user)
):
    """
    清空当前用户的长期记忆。

    可选参数：
    - memory_type: 仅清空指定类型的记忆
    """
    query = LongMemory.filter(user_id=str(current_user.user_id))

    if memory_type:
        query = query.filter(memory_type=memory_type)

    deleted_count = await query.delete()

    return {"message": f"已删除 {deleted_count} 条记忆"}
