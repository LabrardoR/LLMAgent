from fastapi import APIRouter, Depends, HTTPException
from typing import List

from app.schemas.chat import ChatRequest, ConversationOut, MessageOut, ConversationUpdate
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


from fastapi.responses import StreamingResponse


import json

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
            text = ""
            if isinstance(final, dict):
                msgs = final.get("messages") or final.get("output") or final.get("output_messages") or []
                if isinstance(msgs, list) and msgs:
                    last = msgs[-1]
                    text = getattr(last, "content", "") if not isinstance(last, dict) else last.get("content", "")
                elif isinstance(msgs, str):
                    text = msgs
            elif hasattr(final, "get"):
                msgs = final.get("messages", [])
                if msgs:
                    last = msgs[-1]
                    text = getattr(last, "content", "")
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
