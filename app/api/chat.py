"""
聊天 API。

主要能力：
1) 会话与消息管理（增删改查）；
2) SSE 流式对话；
3) 回答重生成；
4) 将短期记忆、长期记忆、RAG 检索上下文统一注入 Agent 输入。
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import List
import logging

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
from app.memory.long_memory import remember_user_facts, search_long_memory
from app.memory.short_memory import get_recent_messages
from app.rag.service import build_rag_context

router = APIRouter()
logger = logging.getLogger(__name__)


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
    naive_time = message.created_time.replace(tzinfo=None)
    await Message.filter(conversation=message.conversation, created_time__gt=naive_time).delete()
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
    """
    基于历史某条用户消息重新生成回答。

    策略：
    - 删除该消息之后的所有消息，保证上下文一致；
    - 重新构建“记忆 + 知识库 + 历史消息”输入后调用 Agent。
    """
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
            created_time__lt=message.created_time.replace(tzinfo=None),
        ).order_by("-created_time").first()
        if not base_message:
            raise HTTPException(status_code=400, detail="找不到可重新生成的用户消息")

    naive_base_time = base_message.created_time.replace(tzinfo=None)
    await Message.filter(conversation=conversation, created_time__gt=naive_base_time).delete()

    # 构建上下文和历史消息
    context_prompt, chat_history = await _build_agent_messages(current_user, conversation, base_message)

    # 创建agent（context_prompt会被注入到system prompt中）
    agent = await get_agent(user_id=str(current_user.user_id), context_prompt=context_prompt)

    # 用户输入
    user_input = base_message.content

    try:
        result = await agent.ainvoke({
            "input": user_input,
            "chat_history": chat_history
        })
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
    """
    兼容不同 LangChain 返回结构，尽量提取纯文本内容。

    该函数用于同步返回与流式失败回退路径，避免因返回格式变化导致解析失败。
    AgentExecutor 返回格式: {"input": ..., "output": ..., "chat_history": ...}
    """
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        # AgentExecutor 返回的 output 字段
        if "output" in result:
            output = result["output"]
            return output if isinstance(output, str) else str(output)

        # 兼容旧格式
        msgs = result.get("messages") or result.get("output_messages") or []
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


async def _build_agent_messages(
    current_user: User,
    conversation: Conversation,
    user_message: Message,
):
    """
    组装模型输入消息列表。

    输入由三部分组成：
    1) 知识库检索上下文（RAG）；
    2) 长期记忆召回内容；
    3) 会话短期历史（不包含当前用户消息）。

    返回：
    - context_prompt: 包含RAG和长期记忆的上下文，将被注入到agent的system prompt中
    - history: 历史对话消息列表（不包含system消息，不包含当前用户消息）
    """
    user_id = str(current_user.user_id)
    conversation_id = str(conversation.conversation_id)

    logger.info(f"Building agent messages for user {user_id}, conversation {conversation_id}")

    # 获取历史消息（当前消息之前的对话历史）
    history = await get_recent_messages(
        conversation_id=conversation_id,
        limit=10,
        before_time=user_message.created_time
    )
    logger.info(f"Retrieved {len(history)} historical messages")

    # 构建RAG上下文
    rag_context = await build_rag_context(user_id=user_id, query=user_message.content, top_k=4)
    if rag_context:
        logger.info(f"RAG context retrieved: {len(rag_context)} characters")

    # 召回长期记忆
    long_memories = await search_long_memory(user_id=user_id, query=user_message.content, top_k=3)
    if long_memories:
        logger.info(f"Recalled {len(long_memories)} long-term memories")

    # 组装上下文提示（将作为system prompt的一部分）
    context_blocks = []
    if rag_context:
        context_blocks.append(f"【知识库检索结果】\n{rag_context}")
    if long_memories:
        context_blocks.append("【长期记忆】\n" + "\n".join(f"- {mem}" for mem in long_memories))

    context_prompt = "\n\n".join(context_blocks)

    if context_prompt:
        logger.debug(f"Context prompt length: {len(context_prompt)} characters")

    # 返回上下文和历史消息
    # 注意：不包含system消息（会由agent内部添加），不包含当前用户消息（会由调用方传入）
    return context_prompt, history

async def stream_generator(chat_request: ChatRequest, current_user: User, conversation: Conversation, created_new: bool):
    """
    SSE 事件生成器。

    流程：
    - 写入用户消息并尝试抽取长期记忆；
    - 组装上下文并流式调用 Agent；
    - 按 token 推送到前端；
    - 对流式空输出场景进行同步回退；
    - 最终持久化 assistant 消息。
    """
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

    user_message = await Message.create(
        conversation=conversation,
        user=current_user,
        role="user",
        content=user_input
    )

    await remember_user_facts(
        user_id=str(current_user.user_id),
        text=user_input,
        source_message_id=user_message.message_id
    )

    # 构建上下文和历史消息
    context_prompt, chat_history = await _build_agent_messages(current_user, conversation, user_message)

    # 创建agent（context_prompt会被注入到system prompt中）
    agent = await get_agent(user_id=str(current_user.user_id), context_prompt=context_prompt)

    full_response = ""
    try:
        async for event in agent.astream_events(
            {"input": user_input, "chat_history": chat_history},
            version="v2",
        ):
            kind = event.get("event")
            if kind in ("on_chat_model_stream", "on_llm_stream"):
                content_part = _extract_text_from_chunk(event["data"]["chunk"])
                if content_part:
                    full_response += content_part
                    yield f"data: {json.dumps({'content': content_part})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return

    if not full_response:
        try:
            final = await agent.ainvoke({
                "input": user_input,
                "chat_history": chat_history
            })
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
    """流式聊天入口，返回 text/event-stream。"""
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
    """非流式聊天入口，返回一次性完整回答。"""
    if not chat_request.messages:
        raise HTTPException(status_code=400, detail="消息列表不能为空")

    if chat_request.conversation_id:
        conversation = await Conversation.get_or_none(conversation_id=chat_request.conversation_id, user=current_user)
        if not conversation:
            raise HTTPException(status_code=404, detail="对话不存在")
    else:
        conversation = await Conversation.create(user=current_user)

    user_input = chat_request.messages[-1].content
    user_message = await Message.create(
        conversation=conversation,
        user=current_user,
        role="user",
        content=user_input
    )
    await remember_user_facts(
        user_id=str(current_user.user_id),
        text=user_input,
        source_message_id=user_message.message_id
    )

    # 构建上下文和历史消息
    context_prompt, chat_history = await _build_agent_messages(current_user, conversation, user_message)

    # 创建agent（context_prompt会被注入到system prompt中）
    agent = await get_agent(user_id=str(current_user.user_id), context_prompt=context_prompt)

    try:
        result = await agent.ainvoke({
            "input": user_input,
            "chat_history": chat_history
        })
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
