from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from app.agent.agent import get_agent
from app.core.security import get_current_user
from app.memory.long_memory import remember_user_facts, search_long_memory
from app.memory.short_memory import (
    get_conversation_summary,
    get_recent_messages,
    suggest_conversation_title,
)
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.rag.service import build_rag_payload
from app.schemas.chat import (
    ChatRequest,
    ConversationBranchRequest,
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    MessageOut,
    MessageUpdate,
    RegenerateRequest,
)

router = APIRouter()


def _json_dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {_json_dumps(payload)}\n\n"


def _chunk_text(content: str, chunk_size: int = 32) -> list[str]:
    return [content[index:index + chunk_size] for index in range(0, len(content), chunk_size)]


def _extract_text_from_agent_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        output = result.get("output")
        if isinstance(output, str):
            return output
        if output is not None:
            return str(output)
        content = result.get("content")
        if isinstance(content, str):
            return content
        if content is not None:
            return str(content)
        return ""
    content = getattr(result, "content", "")
    return content if isinstance(content, str) else str(content)


def _validate_chat_request(chat_request: ChatRequest) -> None:
    if not chat_request.messages:
        raise HTTPException(status_code=400, detail="消息列表不能为空")

    last_message = chat_request.messages[-1]
    if last_message.role != "user":
        raise HTTPException(status_code=400, detail="最后一条消息必须是用户消息")
    if not last_message.content.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")


async def _get_active_conversation(conversation_id: str, current_user: User) -> Conversation:
    conversation = await Conversation.get_or_none(
        conversation_id=conversation_id,
        user=current_user,
        status=1,
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


async def _build_agent_messages(
    current_user: User,
    conversation: Conversation,
    user_message: Message,
    group_name: str | None = None,
    tag: str | None = None,
) -> tuple[str, list[dict[str, str]], list[dict[str, Any]]]:
    history = await get_recent_messages(
        conversation_id=str(conversation.conversation_id),
        limit=10,
        before_time=user_message.created_time,
    )
    rag_payload = await build_rag_payload(
        user_id=str(current_user.user_id),
        query=user_message.content,
        top_k=4,
        group_name=group_name,
        tag=tag,
    )
    long_memories = await search_long_memory(
        user_id=str(current_user.user_id),
        query=user_message.content,
        top_k=3,
    )

    context_parts: list[str] = []
    if rag_payload["context"]:
        context_parts.append(f"【知识库检索结果】\n{rag_payload['context']}")
    if long_memories:
        context_parts.append("【长期记忆】\n" + "\n".join(f"- {item}" for item in long_memories))

    return "\n\n".join(context_parts), history, rag_payload["references"]


async def _maybe_update_conversation_title(conversation: Conversation, user_input: str) -> None:
    if conversation.title and conversation.title != "新对话":
        return
    conversation.title = suggest_conversation_title(user_input)
    await conversation.save()


async def _save_assistant_message(
    conversation: Conversation,
    current_user: User,
    content: str,
) -> Message | None:
    if not content:
        return None
    return await Message.create(
        conversation=conversation,
        user=current_user,
        role="assistant",
        content=content,
    )


def _build_chat_response(
    conversation: Conversation,
    content: str,
    references: list[dict[str, Any]],
    agent_result: dict[str, Any],
    message_id: str | None = None,
) -> dict[str, Any]:
    return {
        "conversation_id": str(conversation.conversation_id),
        "message_id": message_id,
        "content": content,
        "references": references,
        "tool_calls": agent_result.get("tool_calls", []),
        "selected_model": agent_result.get("selected_model"),
        "resolved_model": agent_result.get("resolved_model"),
        "duration_ms": agent_result.get("duration_ms", 0),
    }


async def _run_agent_for_message(
    chat_request: ChatRequest,
    current_user: User,
    conversation: Conversation,
    user_message: Message,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    context_prompt, chat_history, references = await _build_agent_messages(
        current_user=current_user,
        conversation=conversation,
        user_message=user_message,
        group_name=chat_request.group_name,
        tag=chat_request.tag,
    )
    agent = await get_agent(
        user_id=str(current_user.user_id),
        context_prompt=context_prompt,
        conversation_id=str(conversation.conversation_id),
        message_id=str(user_message.message_id),
        reference_count=len(references),
    )
    result = await agent.ainvoke(
        {
            "input": user_message.content,
            "chat_history": chat_history,
        }
    )
    return result, references


@router.get("/conversations", response_model=list[ConversationOut], summary="获取当前用户的所有会话")
async def get_user_conversations(current_user: User = Depends(get_current_user)):
    return await Conversation.filter(user=current_user, status=1).order_by("-updated_time")


@router.get("/conversations/search", summary="搜索会话")
async def search_conversations(
    keyword: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
):
    keyword_lower = keyword.strip().lower()
    conversations = await Conversation.filter(user=current_user, status=1).order_by("-updated_time")
    results: list[dict[str, Any]] = []

    for conversation in conversations:
        matched_in_title = keyword_lower in (conversation.title or "").lower()
        messages = await Message.filter(conversation=conversation).order_by("-created_time").limit(20)
        matched_messages = [msg for msg in messages if keyword_lower in (msg.content or "").lower()]
        if not matched_in_title and not matched_messages:
            continue

        snippet = matched_messages[0].content[:160] if matched_messages else conversation.title
        results.append(
            {
                "conversation_id": str(conversation.conversation_id),
                "title": conversation.title,
                "matched_in_title": matched_in_title,
                "match_count": len(matched_messages),
                "snippet": snippet,
                "updated_time": conversation.updated_time,
            }
        )
        if len(results) >= limit:
            break

    return results


@router.post("/conversations", summary="创建新会话")
async def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
):
    conversation = await Conversation.create(user=current_user, title=payload.title)
    return {"conversation_id": str(conversation.conversation_id)}


@router.get("/conversations/{conversation_id}", response_model=list[MessageOut], summary="获取单个会话的所有消息")
async def get_conversation_messages(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_active_conversation(conversation_id, current_user)
    return await Message.filter(conversation=conversation).order_by("created_time")


@router.get("/conversations/{conversation_id}/summary", summary="获取会话摘要")
async def conversation_summary(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_active_conversation(conversation_id, current_user)
    summary = await get_conversation_summary(str(conversation.conversation_id))
    return {
        "conversation_id": str(conversation.conversation_id),
        "title": conversation.title,
        "summary": summary,
    }


@router.get("/conversations/{conversation_id}/stats", summary="获取会话统计信息")
async def conversation_stats(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
):
    from app.models.chat_run_log import ChatRunLog
    from app.models.tool_call_log import ToolCallLog

    conversation = await _get_active_conversation(conversation_id, current_user)
    messages = await Message.filter(conversation=conversation).order_by("created_time")
    run_logs = await ChatRunLog.filter(conversation=conversation).order_by("-created_time")
    tool_logs = await ToolCallLog.filter(conversation=conversation).order_by("-created_time")

    user_count = len([item for item in messages if item.role == "user"])
    assistant_count = len([item for item in messages if item.role == "assistant"])
    avg_duration = round(sum(item.duration_ms for item in run_logs) / len(run_logs), 2) if run_logs else 0

    return {
        "conversation_id": str(conversation.conversation_id),
        "title": conversation.title,
        "message_count": len(messages),
        "user_message_count": user_count,
        "assistant_message_count": assistant_count,
        "tool_call_count": len(tool_logs),
        "avg_duration_ms": avg_duration,
        "last_message_time": messages[-1].created_time if messages else None,
        "summary": await get_conversation_summary(str(conversation.conversation_id)),
    }


@router.get("/conversations/{conversation_id}/export", summary="导出会话")
async def export_conversation(
    conversation_id: str,
    format: str = "markdown",
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_active_conversation(conversation_id, current_user)
    messages = await Message.filter(conversation=conversation).order_by("created_time")

    if format == "json":
        return JSONResponse(
            {
                "conversation_id": str(conversation.conversation_id),
                "title": conversation.title,
                "messages": [
                    {
                        "message_id": str(item.message_id),
                        "role": item.role,
                        "content": item.content,
                        "created_time": item.created_time.isoformat(),
                    }
                    for item in messages
                ],
            }
        )

    if format == "text":
        content = "\n\n".join(f"[{item.role}] {item.content}" for item in messages)
        return PlainTextResponse(content)

    lines = [f"# {conversation.title}", ""]
    for item in messages:
        lines.append(f"## {item.role}")
        lines.append(item.content)
        lines.append("")
    return PlainTextResponse("\n".join(lines), media_type="text/markdown")


@router.post("/conversations/{conversation_id}/branch", summary="创建分支会话")
async def branch_conversation(
    conversation_id: str,
    payload: ConversationBranchRequest,
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_active_conversation(conversation_id, current_user)
    source_messages = await Message.filter(conversation=conversation).order_by("created_time")

    if payload.message_id:
        target = await Message.get_or_none(
            message_id=payload.message_id,
            conversation=conversation,
            user=current_user,
        )
        if not target:
            raise HTTPException(status_code=404, detail="消息不存在")

        filtered: list[Message] = []
        cutoff = target.created_time.replace(tzinfo=None)
        for item in source_messages:
            created_time = item.created_time.replace(tzinfo=None) if item.created_time.tzinfo else item.created_time
            if created_time <= cutoff:
                filtered.append(item)
        source_messages = filtered

    new_conversation = await Conversation.create(user=current_user, title=payload.title)
    for item in source_messages:
        await Message.create(
            conversation=new_conversation,
            user=current_user,
            role=item.role,
            content=item.content,
            message_type=item.message_type,
            tokens=item.tokens,
        )

    return {"conversation_id": str(new_conversation.conversation_id)}


@router.put("/conversations/{conversation_id}", summary="修改会话标题")
async def update_conversation_title(
    conversation_id: str,
    update_data: ConversationUpdate,
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_active_conversation(conversation_id, current_user)
    conversation.title = update_data.title
    await conversation.save()
    return {"message": "会话标题已更新"}


@router.delete("/conversations/{conversation_id}", summary="删除会话")
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_active_conversation(conversation_id, current_user)
    conversation.status = 0
    await conversation.save()
    return {"message": "会话已删除"}


@router.delete("/conversations/{conversation_id}/messages", summary="清空会话")
async def clear_conversation_messages(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_active_conversation(conversation_id, current_user)
    await Message.filter(conversation=conversation).delete()
    return {"message": "会话已清空"}


@router.put("/messages/{message_id}", summary="编辑消息")
async def update_message(
    message_id: str,
    payload: MessageUpdate,
    current_user: User = Depends(get_current_user),
):
    message = await Message.get_or_none(message_id=message_id, user=current_user, conversation__status=1)
    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")

    message.content = payload.content
    await message.save()

    compare_time = message.created_time.replace(tzinfo=None) if message.created_time.tzinfo else message.created_time
    await Message.filter(
        conversation=message.conversation,
        created_time__gt=compare_time,
    ).delete()
    return {"message": "消息已更新"}


@router.delete("/messages/{message_id}", summary="删除单条消息")
async def delete_message(
    message_id: str,
    current_user: User = Depends(get_current_user),
):
    message = await Message.get_or_none(message_id=message_id, user=current_user, conversation__status=1)
    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")
    await message.delete()
    return {"message": "消息已删除"}


@router.post("/regenerate", summary="重新生成回答")
async def regenerate(
    payload: RegenerateRequest,
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_active_conversation(str(payload.conversation_id), current_user)
    message = await Message.get_or_none(
        message_id=payload.message_id,
        user=current_user,
        conversation=conversation,
    )
    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")

    base_message = message
    if base_message.role != "user":
        compare_time = base_message.created_time.replace(tzinfo=None) if base_message.created_time.tzinfo else base_message.created_time
        base_message = await Message.filter(
            conversation=conversation,
            user=current_user,
            role="user",
            created_time__lt=compare_time,
        ).order_by("-created_time").first()
        if not base_message:
            raise HTTPException(status_code=400, detail="找不到可重新生成的用户消息")

    compare_time = base_message.created_time.replace(tzinfo=None) if base_message.created_time.tzinfo else base_message.created_time
    await Message.filter(conversation=conversation, created_time__gt=compare_time).delete()

    request = ChatRequest(
        conversation_id=conversation.conversation_id,
        messages=[{"role": "user", "content": base_message.content}],
    )
    agent_result, references = await _run_agent_for_message(
        chat_request=request,
        current_user=current_user,
        conversation=conversation,
        user_message=base_message,
    )
    content = _extract_text_from_agent_result(agent_result)
    assistant_message = await _save_assistant_message(conversation, current_user, content)

    return _build_chat_response(
        conversation=conversation,
        content=content,
        references=references,
        agent_result=agent_result,
        message_id=str(assistant_message.message_id) if assistant_message else None,
    )


async def stream_generator(
    chat_request: ChatRequest,
    current_user: User,
    conversation: Conversation,
    created_new: bool,
    request: Request,
):
    if created_new:
        yield _sse_event("conversation", {"conversation_id": str(conversation.conversation_id)})

    user_input = chat_request.messages[-1].content.strip()
    await _maybe_update_conversation_title(conversation, user_input)

    user_message = await Message.create(
        conversation=conversation,
        user=current_user,
        role="user",
        content=user_input,
    )
    await remember_user_facts(
        user_id=str(current_user.user_id),
        text=user_input,
        source_message_id=user_message.message_id,
    )
    yield _sse_event(
        "message",
        {
            "conversation_id": str(conversation.conversation_id),
            "user_message_id": str(user_message.message_id),
            "status": "started",
        },
    )

    context_prompt, chat_history, references = await _build_agent_messages(
        current_user=current_user,
        conversation=conversation,
        user_message=user_message,
        group_name=chat_request.group_name,
        tag=chat_request.tag,
    )
    agent = await get_agent(
        user_id=str(current_user.user_id),
        context_prompt=context_prompt,
        conversation_id=str(conversation.conversation_id),
        message_id=str(user_message.message_id),
        reference_count=len(references),
    )

    final_result: dict[str, Any] = {}
    task = asyncio.create_task(
        agent.ainvoke(
            {
                "input": user_input,
                "chat_history": chat_history,
            }
        )
    )

    try:
        while True:
            if await request.is_disconnected():
                task.cancel()
                return
            try:
                final_result = await asyncio.wait_for(asyncio.shield(task), timeout=8)
                break
            except asyncio.TimeoutError:
                yield _sse_event("ping", {"timestamp": int(time.time())})

        content = _extract_text_from_agent_result(final_result)
        if content:
            for chunk_text in _chunk_text(content):
                if await request.is_disconnected():
                    return
                yield _sse_event("token", {"content": chunk_text})
                await asyncio.sleep(0)

        assistant_message = await _save_assistant_message(conversation, current_user, content)
        yield _sse_event("references", {"references": references})
        yield _sse_event("tool_calls", {"tool_calls": final_result.get("tool_calls", [])})
        yield _sse_event(
            "meta",
            {
                "selected_model": final_result.get("selected_model"),
                "resolved_model": final_result.get("resolved_model"),
                "duration_ms": final_result.get("duration_ms", 0),
            },
        )
        yield _sse_event(
            "done",
            {
                "conversation_id": str(conversation.conversation_id),
                "message_id": str(assistant_message.message_id) if assistant_message else None,
                "done": True,
            },
        )
    except asyncio.CancelledError:
        task.cancel()
        raise
    except Exception as exc:
        if not task.done():
            task.cancel()
        yield _sse_event(
            "error",
            {
                "conversation_id": str(conversation.conversation_id),
                "error": str(exc),
                "done": True,
            },
        )


@router.post("/", summary="聊天")
async def chat(
    chat_request: ChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _validate_chat_request(chat_request)

    created_new = False
    if chat_request.conversation_id:
        conversation = await _get_active_conversation(str(chat_request.conversation_id), current_user)
    else:
        conversation = await Conversation.create(user=current_user)
        created_new = True

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        stream_generator(chat_request, current_user, conversation, created_new, request),
        media_type="text/event-stream",
        headers=headers,
    )


@router.post("/sync", summary="聊天(非流式)")
async def chat_sync(
    chat_request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    _validate_chat_request(chat_request)

    if chat_request.conversation_id:
        conversation = await _get_active_conversation(str(chat_request.conversation_id), current_user)
    else:
        conversation = await Conversation.create(user=current_user)

    user_input = chat_request.messages[-1].content.strip()
    await _maybe_update_conversation_title(conversation, user_input)

    user_message = await Message.create(
        conversation=conversation,
        user=current_user,
        role="user",
        content=user_input,
    )
    await remember_user_facts(
        user_id=str(current_user.user_id),
        text=user_input,
        source_message_id=user_message.message_id,
    )

    agent_result, references = await _run_agent_for_message(
        chat_request=chat_request,
        current_user=current_user,
        conversation=conversation,
        user_message=user_message,
    )
    content = _extract_text_from_agent_result(agent_result)
    assistant_message = await _save_assistant_message(conversation, current_user, content)
    return _build_chat_response(
        conversation=conversation,
        content=content,
        references=references,
        agent_result=agent_result,
        message_id=str(assistant_message.message_id) if assistant_message else None,
    )
