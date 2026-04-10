"""
聊天 API。

能力：
1. 会话和消息管理；
2. SSE 聊天；
3. 回答重新生成；
4. 短期记忆、长期记忆、RAG 统一注入；
5. 会话摘要、导出、分支、统计。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
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


def _extract_text_from_chunk(chunk: Any) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    text_parts.append(str(text))
        return "".join(text_parts)
    return str(content)


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

    context_prompt = "\n\n".join(context_parts)
    return context_prompt, history, rag_payload["references"]


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
    messages_query = Message.filter(conversation=conversation).order_by("created_time")
    source_messages = await messages_query

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
):
    if created_new:
        yield f"data: {json.dumps({'conversation_id': str(conversation.conversation_id)})}\n\n"

    user_input = chat_request.messages[-1].content
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

    full_response = ""
    final_result: dict[str, Any] = {}
    try:
        async for event in agent.astream_events(
            {"input": user_input, "chat_history": chat_history},
            version="v2",
        ):
            event_name = event.get("event")
            if event_name in {"on_chat_model_stream", "on_llm_stream"}:
                chunk_text = _extract_text_from_chunk(event["data"]["chunk"])
                if not chunk_text:
                    continue
                full_response += chunk_text
                yield f"data: {json.dumps({'content': chunk_text})}\n\n"
            elif event_name == "on_chat_model_end":
                final_result = event["data"].get("result", {})
    except Exception as exc:
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        return

    if not full_response:
        full_response = _extract_text_from_agent_result(final_result)
        if full_response:
            yield f"data: {json.dumps({'content': full_response})}\n\n"

    assistant_message = await _save_assistant_message(conversation, current_user, full_response)
    yield f"data: {json.dumps({'references': references})}\n\n"
    yield f"data: {json.dumps({'tool_calls': final_result.get('tool_calls', [])})}\n\n"
    yield f"data: {json.dumps({'selected_model': final_result.get('selected_model'), 'resolved_model': final_result.get('resolved_model'), 'duration_ms': final_result.get('duration_ms', 0)})}\n\n"
    yield f"data: {json.dumps({'message_id': str(assistant_message.message_id) if assistant_message else None, 'done': True})}\n\n"


@router.post("/", summary="聊天")
async def chat(
    chat_request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    if not chat_request.messages:
        raise HTTPException(status_code=400, detail="消息列表不能为空")

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
        stream_generator(chat_request, current_user, conversation, created_new),
        media_type="text/event-stream",
        headers=headers,
    )


@router.post("/sync", summary="聊天(非流式)")
async def chat_sync(
    chat_request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    if not chat_request.messages:
        raise HTTPException(status_code=400, detail="消息列表不能为空")

    if chat_request.conversation_id:
        conversation = await _get_active_conversation(str(chat_request.conversation_id), current_user)
    else:
        conversation = await Conversation.create(user=current_user)

    user_input = chat_request.messages[-1].content
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
