from fastapi import APIRouter, Depends, HTTPException
from typing import List

from app.schemas.chat import (
    ChatRequest,
    ConversationOut,
    MessageOut,
    ConversationUpdate,
    ConversationCreate,
    MessageUpdate,
    RegenerateRequest,
)
from app.models.user import User
from app.models.conversation import Conversation
from app.models.message import Message
from app.core.security import get_current_user
from app.agent.agent import get_agent

router = APIRouter()


@router.get("/conversations", response_model=List[ConversationOut], summary="获取当前用户的所有会话")
async def get_user_conversations(current_user: User = Depends(get_current_user)):
    conversations = await Conversation.filter(user=current_user, status=1).order_by("-created_time")
    return conversations


@router.post("/conversations", summary="创建新会话")
async def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user)
):
    conversation = await Conversation.create(user=current_user, title=payload.title)
    return {"conversation_id": str(conversation.conversation_id)}


@router.get("/conversations/{conversation_id}", response_model=List[MessageOut], summary="获取单个会话的所有消息")
async def get_conversation_messages(
    conversation_id: str,
    current_user: User = Depends(get_current_user)
):
    conversation = await Conversation.get_or_none(conversation_id=conversation_id, user=current_user)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    messages = await Message.filter(conversation=conversation).order_by("created_time")
    return messages


@router.put("/conversations/{conversation_id}", summary="修改会话标题")
async def update_conversation_title(
    conversation_id: str,
    update_data: ConversationUpdate,
    current_user: User = Depends(get_current_user)
):
    conversation = await Conversation.get_or_none(conversation_id=conversation_id, user=current_user)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    conversation.title = update_data.title
    await conversation.save()
    return {"message": "会话标题已更新"}


@router.delete("/conversations/{conversation_id}", summary="删除会话")
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user)
):
    conversation = await Conversation.get_or_none(conversation_id=conversation_id, user=current_user, status=1)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    conversation.status = 0
    await conversation.save()
    return {"message": "会话已删除"}


@router.delete("/conversations/{conversation_id}/messages", summary="清空会话")
async def clear_conversation_messages(
    conversation_id: str,
    current_user: User = Depends(get_current_user)
):
    conversation = await Conversation.get_or_none(conversation_id=conversation_id, user=current_user, status=1)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    await Message.filter(conversation=conversation).delete()
    return {"message": "会话已清空"}


@router.put("/messages/{message_id}", summary="编辑消息")
async def update_message(
    message_id: str,
    payload: MessageUpdate,
    current_user: User = Depends(get_current_user)
):
    message = await Message.get_or_none(message_id=message_id, user=current_user)
    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")
    message.content = payload.content
    await message.save()
    await Message.filter(conversation=message.conversation, created_time__gt=message.created_time).delete()
    return {"message": "消息已更新"}


@router.delete("/messages/{message_id}", summary="删除单条消息")
async def delete_message(
    message_id: str,
    current_user: User = Depends(get_current_user)
):
    message = await Message.get_or_none(message_id=message_id, user=current_user)
    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")
    await message.delete()
    return {"message": "消息已删除"}


@router.post("/regenerate", summary="重新生成回答")
async def regenerate(
    payload: RegenerateRequest,
    current_user: User = Depends(get_current_user)
):
    conversation = await Conversation.get_or_none(conversation_id=payload.conversation_id, user=current_user, status=1)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")

    message = await Message.get_or_none(message_id=payload.message_id, user=current_user, conversation=conversation)
    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")

    base_message = message
    if base_message.role != "user":
        base_message = await Message.filter(
            conversation=conversation,
            user=current_user,
            role="user",
            created_time__lt=message.created_time,
        ).order_by("-created_time").first()
        if not base_message:
            raise HTTPException(status_code=400, detail="找不到可重新生成的用户消息")

    await Message.filter(conversation=conversation, created_time__gt=base_message.created_time).delete()

    agent = get_agent(user_id=str(current_user.user_id))
    try:
        result = await agent.ainvoke({"messages": [{"role": "user", "content": base_message.content}]})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    content = _extract_text_from_agent_result(result)
    new_message_id = None
    if content:
        new_msg = await Message.create(
            conversation=conversation,
            user=current_user,
            role="assistant",
            content=content
        )
        new_message_id = str(new_msg.message_id)

    return {
        "conversation_id": str(conversation.conversation_id),
        "message_id": new_message_id,
        "content": content
    }


from fastapi.responses import StreamingResponse


import json

def _extract_text_from_agent_result(result) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        msgs = result.get("messages") or result.get("output") or result.get("output_messages") or []
        if isinstance(msgs, list) and msgs:
            last = msgs[-1]
            if isinstance(last, dict):
                content = last.get("content", "")
                return content if isinstance(content, str) else str(content)
            return getattr(last, "content", "") or ""
        if isinstance(msgs, str):
            return msgs
        content = result.get("content")
        if isinstance(content, str):
            return content
        if content is not None:
            return str(content)
        return ""
    if hasattr(result, "content"):
        content = getattr(result, "content")
        if isinstance(content, str):
            return content
        if content is not None:
            return str(content)
    if hasattr(result, "get"):
        msgs = result.get("messages", [])
        if msgs:
            last = msgs[-1]
            return getattr(last, "content", "") or ""
    return str(result) if result is not None else ""

async def stream_generator(chat_request: ChatRequest, current_user: User, conversation: Conversation, created_new: bool):
    def _extract_text_from_chunk(chunk) -> str:
        try:
            content = getattr(chunk, "content", None)
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                text = ""
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text += part.get("text", "")
                    else:
                        t = getattr(part, "text", None)
                        if t:
                            text += t
                return text
            if content is not None:
                return str(content)
        except Exception:
            pass
        return ""

    if created_new:
        yield f"data: {json.dumps({'conversation_id': str(conversation.conversation_id)})}\n\n"

    user_input = chat_request.messages[-1].content

    await Message.create(
        conversation=conversation,
        user=current_user,
        role="user",
        content=user_input
    )

    agent = get_agent(user_id=str(current_user.user_id))
    full_response = ""
    try:
        async for event in agent.astream_events(
            {"messages": [{"role": "user", "content": user_input}]},
            version="v1",
        ):
            # 仅在模型逐token输出事件时推送到前端
            ev = event.get("event")
            if ev in ("on_chat_model_stream", "on_llm_stream"):
                content_part = _extract_text_from_chunk(event["data"]["chunk"])
                if content_part:
                    full_response += content_part
                    yield f"data: {json.dumps({'content': content_part})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return

    # 保存完整的模型响应
    if not full_response:
        try:
            final = await agent.ainvoke({"messages": [{"role": "user", "content": user_input}]})
            text = _extract_text_from_agent_result(final)
            if text:
                full_response = text
                yield f"data: {json.dumps({'content': text})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return
    if full_response:
        await Message.create(
            conversation=conversation,
            user=current_user,
            role="assistant",
            content=full_response
        )

@router.post("/", summary="聊天")
async def chat(
    chat_request: ChatRequest,
    current_user: User = Depends(get_current_user)
):
    if not chat_request.messages:
        raise HTTPException(status_code=400, detail="消息列表不能为空")

    created_new = False
    if chat_request.conversation_id:
        conversation = await Conversation.get_or_none(conversation_id=chat_request.conversation_id, user=current_user)
        if not conversation:
            raise HTTPException(status_code=404, detail="对话不存在")
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
    current_user: User = Depends(get_current_user)
):
    if not chat_request.messages:
        raise HTTPException(status_code=400, detail="消息列表不能为空")

    if chat_request.conversation_id:
        conversation = await Conversation.get_or_none(conversation_id=chat_request.conversation_id, user=current_user)
        if not conversation:
            raise HTTPException(status_code=404, detail="对话不存在")
    else:
        conversation = await Conversation.create(user=current_user)

    user_input = chat_request.messages[-1].content
    await Message.create(
        conversation=conversation,
        user=current_user,
        role="user",
        content=user_input
    )

    agent = get_agent(user_id=str(current_user.user_id))
    try:
        result = await agent.ainvoke({"messages": [{"role": "user", "content": user_input}]})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    content = _extract_text_from_agent_result(result)
    if content:
        await Message.create(
            conversation=conversation,
            user=current_user,
            role="assistant",
            content=content
        )

    return {
        "conversation_id": str(conversation.conversation_id),
        "content": content
    }
