"""
记忆管理 API。

提供长期记忆的查看、创建、修改、删除、确认和统计功能。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.memory.long_memory import _record_memory_event, _resolve_conflicts
from app.models.long_memory import LongMemory
from app.models.memory_event import MemoryEvent
from app.models.memory_meta import MemoryMeta
from app.models.user import User
from app.rag.vector_store import get_embeddings_model
from app.schemas.memory import (
    LongMemoryConfirmRequest,
    LongMemoryCreate,
    LongMemoryOut,
    LongMemoryUpdate,
    MemoryStatsOut,
)

router = APIRouter()


async def _build_memory_out(memory: LongMemory) -> LongMemoryOut:
    meta = await MemoryMeta.get_or_none(memory=memory)
    return LongMemoryOut(
        memory_id=str(memory.memory_id),
        memory_type=memory.memory_type,
        content=memory.content,
        hit_count=memory.hit_count,
        confidence=meta.confidence if meta else 0.0,
        confirmed=bool(meta.confirmed) if meta else False,
        source=meta.source if meta else "manual",
        created_time=memory.created_time,
    )


@router.get("/long-memories", response_model=list[LongMemoryOut], summary="获取所有长期记忆")
async def get_long_memories(
    memory_type: str | None = None,
    confirmed: bool | None = None,
    current_user: User = Depends(get_current_user),
):
    query = LongMemory.filter(user_id=str(current_user.user_id))
    if memory_type:
        query = query.filter(memory_type=memory_type)

    memories = await query.order_by("-created_time")
    items: list[LongMemoryOut] = []
    for memory in memories:
        item = await _build_memory_out(memory)
        if confirmed is not None and item.confirmed != confirmed:
            continue
        items.append(item)
    return items


@router.get("/long-memories/stats", response_model=MemoryStatsOut, summary="获取记忆统计信息")
async def get_memory_stats(current_user: User = Depends(get_current_user)):
    user_id = str(current_user.user_id)
    memories = await LongMemory.filter(user_id=user_id).all()
    meta_records = await MemoryMeta.filter(memory__user_id=user_id)
    meta_map = {str(item.memory_id): item for item in meta_records}

    by_type: dict[str, int] = {}
    total_confidence = 0.0
    confirmed_count = 0
    outputs: list[LongMemoryOut] = []

    for memory in memories:
        by_type[memory.memory_type] = by_type.get(memory.memory_type, 0) + 1
        meta = meta_map.get(str(memory.memory_id))
        if meta:
            total_confidence += meta.confidence
            if meta.confirmed:
                confirmed_count += 1
        outputs.append(await _build_memory_out(memory))

    most_accessed = sorted(outputs, key=lambda item: item.hit_count, reverse=True)[:5]
    average_confidence = round(total_confidence / len(memories), 4) if memories else 0.0

    return MemoryStatsOut(
        total_memories=len(memories),
        confirmed_memories=confirmed_count,
        average_confidence=average_confidence,
        by_type=by_type,
        most_accessed=most_accessed,
    )


@router.get("/long-memories/events", summary="获取记忆事件日志")
async def get_memory_events(limit: int = 20, current_user: User = Depends(get_current_user)):
    events = await MemoryEvent.filter(user=current_user).order_by("-created_time").limit(limit)
    return [
        {
            "event_id": str(item.event_id),
            "memory_type": item.memory_type,
            "action": item.action,
            "old_content": item.old_content,
            "new_content": item.new_content,
            "note": item.note,
            "created_time": item.created_time,
        }
        for item in events
    ]


@router.post("/long-memories", response_model=LongMemoryOut, summary="手动创建长期记忆")
async def create_long_memory(
    payload: LongMemoryCreate,
    current_user: User = Depends(get_current_user),
):
    user_id = str(current_user.user_id)
    await _resolve_conflicts(user_id=user_id, memory_type=payload.memory_type, content=payload.content)

    exists = await LongMemory.filter(
        user_id=user_id,
        memory_type=payload.memory_type,
        content=payload.content,
    ).exists()
    if exists:
        raise HTTPException(status_code=400, detail="该记忆已存在")

    try:
        embedding = get_embeddings_model().embed_query(payload.content)
    except Exception:
        embedding = None

    memory = await LongMemory.create(
        user_id=user_id,
        memory_type=payload.memory_type,
        content=payload.content,
        embedding=embedding,
    )
    await MemoryMeta.create(
        memory=memory,
        confidence=payload.confidence,
        confirmed=True,
        source="manual",
    )
    await _record_memory_event(
        user_id=user_id,
        memory_type=payload.memory_type,
        action="created",
        new_content=payload.content,
        note="manual",
    )
    return await _build_memory_out(memory)


@router.put("/long-memories/{memory_id}", response_model=LongMemoryOut, summary="更新长期记忆")
async def update_long_memory(
    memory_id: str,
    payload: LongMemoryUpdate,
    current_user: User = Depends(get_current_user),
):
    memory = await LongMemory.get_or_none(memory_id=memory_id, user_id=str(current_user.user_id))
    if not memory:
        raise HTTPException(status_code=404, detail="记忆不存在")

    old_content = memory.content
    await _resolve_conflicts(
        user_id=str(current_user.user_id),
        memory_type=memory.memory_type,
        content=payload.content,
    )

    memory.content = payload.content
    try:
        memory.embedding = get_embeddings_model().embed_query(payload.content)
    except Exception:
        pass
    await memory.save()

    meta = await MemoryMeta.get_or_none(memory=memory)
    if not meta:
        meta = await MemoryMeta.create(memory=memory, source="manual")
    if payload.confidence is not None:
        meta.confidence = payload.confidence
    meta.source = "manual"
    await meta.save()

    await _record_memory_event(
        user_id=str(current_user.user_id),
        memory_type=memory.memory_type,
        action="updated",
        old_content=old_content,
        new_content=payload.content,
        note="manual",
    )
    return await _build_memory_out(memory)


@router.post("/long-memories/{memory_id}/confirm", response_model=LongMemoryOut, summary="确认或取消确认记忆")
async def confirm_long_memory(
    memory_id: str,
    payload: LongMemoryConfirmRequest,
    current_user: User = Depends(get_current_user),
):
    memory = await LongMemory.get_or_none(memory_id=memory_id, user_id=str(current_user.user_id))
    if not memory:
        raise HTTPException(status_code=404, detail="记忆不存在")

    meta = await MemoryMeta.get_or_none(memory=memory)
    if not meta:
        meta = await MemoryMeta.create(memory=memory, confidence=0.8, source="manual")
    meta.confirmed = payload.confirmed
    await meta.save()

    await _record_memory_event(
        user_id=str(current_user.user_id),
        memory_type=memory.memory_type,
        action="confirmed" if payload.confirmed else "unconfirmed",
        new_content=memory.content,
        note="user action",
    )
    return await _build_memory_out(memory)


@router.delete("/long-memories/{memory_id}", summary="删除长期记忆")
async def delete_long_memory(memory_id: str, current_user: User = Depends(get_current_user)):
    memory = await LongMemory.get_or_none(memory_id=memory_id, user_id=str(current_user.user_id))
    if not memory:
        raise HTTPException(status_code=404, detail="记忆不存在")

    content = memory.content
    memory_type = memory.memory_type
    await MemoryMeta.filter(memory=memory).delete()
    await memory.delete()
    await _record_memory_event(
        user_id=str(current_user.user_id),
        memory_type=memory_type,
        action="deleted",
        old_content=content,
        note="manual delete",
    )
    return {"message": "记忆已删除"}


@router.delete("/long-memories", summary="清空所有长期记忆")
async def clear_long_memories(
    memory_type: str | None = None,
    current_user: User = Depends(get_current_user),
):
    query = LongMemory.filter(user_id=str(current_user.user_id))
    if memory_type:
        query = query.filter(memory_type=memory_type)

    memories = await query.all()
    memory_ids = [item.memory_id for item in memories]
    deleted_count = len(memories)

    if memory_ids:
        await MemoryMeta.filter(memory_id__in=memory_ids).delete()
    await query.delete()
    return {"message": f"已删除 {deleted_count} 条记忆"}
