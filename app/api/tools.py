"""
工具管理 API。

提供：
1. 工具列表；
2. 工具启用/禁用；
3. 工具热重载；
4. 工具统计和调用日志。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agent.agent import (
    get_available_tools,
    get_tools_enabled,
    reload_extension_tools,
    set_tool_enabled,
)
from app.core.security import get_current_user

router = APIRouter()


class ToolToggleRequest(BaseModel):
    tool_name: str
    enabled: bool


@router.get("", summary="获取工具列表")
async def list_tools(current_user=Depends(get_current_user)):
    return await get_available_tools(str(current_user.user_id))


@router.get("/stats", summary="获取工具使用统计")
async def tool_stats(current_user=Depends(get_current_user)):
    from app.models.tool_call_log import ToolCallLog

    logs = await ToolCallLog.filter(user=current_user).order_by("-created_time").limit(200)
    stats: dict[str, dict[str, int]] = {}

    for item in logs:
        target = stats.setdefault(
            item.tool_name,
            {"count": 0, "success_count": 0, "latency_ms": 0},
        )
        target["count"] += 1
        target["latency_ms"] += item.latency_ms
        if item.success:
            target["success_count"] += 1

    items = []
    for name, item in stats.items():
        count = item["count"] or 1
        items.append(
            {
                "tool_name": name,
                "count": item["count"],
                "success_count": item["success_count"],
                "success_rate": round(item["success_count"] / count, 4),
                "avg_latency_ms": round(item["latency_ms"] / count, 2),
            }
        )
    return {"items": items}


@router.get("/logs", summary="获取工具调用日志")
async def tool_logs(limit: int = 20, current_user=Depends(get_current_user)):
    from app.models.tool_call_log import ToolCallLog

    logs = await ToolCallLog.filter(user=current_user).order_by("-created_time").limit(limit)
    return [
        {
            "log_id": str(item.log_id),
            "tool_name": item.tool_name,
            "input_text": item.input_text,
            "output_text": item.output_text,
            "success": item.success,
            "latency_ms": item.latency_ms,
            "conversation_id": str(item.conversation_id) if item.conversation_id else None,
            "message_id": str(item.message_id) if item.message_id else None,
            "created_time": item.created_time,
        }
        for item in logs
    ]


@router.post("/toggle", summary="启用/禁用工具")
async def toggle_tool(payload: ToolToggleRequest, current_user=Depends(get_current_user)):
    try:
        await set_tool_enabled(str(current_user.user_id), payload.tool_name, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="不支持的工具") from exc

    enabled_tools = await get_tools_enabled(str(current_user.user_id))
    return {
        "tool_name": payload.tool_name,
        "enabled": bool(enabled_tools.get(payload.tool_name, True)),
    }


@router.post("/reload", summary="重载扩展工具")
async def reload_tools(current_user=Depends(get_current_user)):
    reload_extension_tools()
    return await get_available_tools(str(current_user.user_id))
