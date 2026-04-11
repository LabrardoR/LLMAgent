"""
长期记忆模块。

核心流程：
1. 从用户输入中抽取结构化事实；
2. 持久化到 LongMemory；
3. 为记忆补充置信度和确认状态；
4. 在新问题到来时按相关性召回。
"""

from __future__ import annotations

import math
import os
import re
import json
from typing import Any

from app.models.long_memory import LongMemory
from app.models.memory_event import MemoryEvent
from app.models.memory_meta import MemoryMeta
from app.rag.vector_store import get_embeddings_model

_EXCLUSIVE_TYPES = {"name", "city", "job", "age", "education"}

_PATTERNS: list[tuple[re.Pattern[str], str, str, float]] = [
    (re.compile(r"(?:我叫|我的名字是|叫我)([^\s，。！？]{1,20})"), "name", "用户姓名是{value}", 0.95),
    (re.compile(r"(?:我来自|我住在|我现在住在|我的城市是)([^\s，。！？]{1,20})"), "city", "用户所在城市是{value}", 0.9),
    (re.compile(r"(?:我的职业是|我从事|我是一名|我是个)([^\s，。！？]{1,30})"), "job", "用户职业是{value}", 0.88),
    (re.compile(r"(?:我今年)(\d{1,3})(?:岁|周岁)"), "age", "用户年龄是{value}岁", 0.92),
    (re.compile(r"(?:我喜欢|我的爱好是|我平时喜欢)([^\n，。！？]{1,50})"), "hobby", "用户的爱好是{value}", 0.82),
    (re.compile(r"(?:我擅长|我精通|我熟悉)([^\n，。！？]{1,50})"), "skill", "用户擅长{value}", 0.85),
    (re.compile(r"(?:我不喜欢|我讨厌)([^\n，。！？]{1,50})"), "dislike", "用户不喜欢{value}", 0.8),
    (re.compile(r"(?:我会说|我掌握)([^\s，。！？]{1,20})(?:语|话)?"), "language", "用户会说{value}", 0.83),
    (re.compile(r"(?:我在做|我正在做|我的项目是)([^\n，。！？]{1,60})"), "project", "用户的项目是{value}", 0.8),
    (re.compile(r"(?:我毕业于|我就读于)([^\s，。！？]{1,30})"), "education", "用户毕业于{value}", 0.88),
]


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    numerator = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return numerator / (norm1 * norm2)


def extract_long_term_facts_with_regex(text: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for pattern, memory_type, template, confidence in _PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        value = match.group(1).strip()
        if not value:
            continue
        facts.append(
            {
                "memory_type": memory_type,
                "content": template.format(value=value),
                "confidence": confidence,
                "source": "regex",
            }
        )
    return facts


async def extract_long_term_facts_with_llm(text: str) -> list[dict[str, Any]]:
    try:
        from langchain_community.chat_models import ChatTongyi

        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            return []

        llm = ChatTongyi(
            model="qwen-turbo",
            dashscope_api_key=api_key,
            temperature=0.1,
        )
        prompt = f"""从下面这段用户输入中抽取明确且稳定的个人信息。

用户输入:
{text}

请只返回 JSON 数组，数组元素格式如下：
[
  {{
    "memory_type": "name/city/job/hobby/age/skill/dislike/language/project/education/other",
    "content": "整理后的完整事实句子",
    "confidence": 0.0
  }}
]

如果没有可提取内容，请返回 []。
不要输出其他解释。"""

        response = await llm.ainvoke(prompt)
        content = getattr(response, "content", "")
        if isinstance(content, list):
            content = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
        content = str(content).strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        items = json.loads(content)
        if not isinstance(items, list):
            return []

        facts: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            memory_type = str(item.get("memory_type", "")).strip() or "other"
            fact_content = str(item.get("content", "")).strip()
            if not fact_content:
                continue
            confidence = float(item.get("confidence", 0.75) or 0.75)
            facts.append(
                {
                    "memory_type": memory_type,
                    "content": fact_content,
                    "confidence": max(0.1, min(confidence, 0.99)),
                    "source": "llm",
                }
            )
        return facts
    except Exception:
        return []


async def extract_long_term_facts(text: str, use_llm: bool = True) -> list[dict[str, Any]]:
    facts = extract_long_term_facts_with_regex(text)
    if facts or not use_llm:
        return facts
    return await extract_long_term_facts_with_llm(text)


async def _ensure_memory_meta(memory: LongMemory, confidence: float, source: str) -> MemoryMeta:
    meta = await MemoryMeta.get_or_none(memory_id=memory.memory_id)
    if meta:
        meta.confidence = confidence
        meta.source = source
        await meta.save()
        return meta

    return await MemoryMeta.create(
        memory=memory,
        confidence=confidence,
        source=source,
    )


async def _record_memory_event(
    user_id: str,
    memory_type: str,
    action: str,
    old_content: str | None = None,
    new_content: str | None = None,
    note: str = "",
) -> None:
    try:
        await MemoryEvent.create(
            user_id=user_id,
            memory_type=memory_type,
            action=action,
            old_content=old_content,
            new_content=new_content,
            note=note,
        )
    except Exception:
        return


async def _resolve_conflicts(user_id: str, memory_type: str, content: str) -> None:
    if memory_type not in _EXCLUSIVE_TYPES:
        return

    existing_items = await LongMemory.filter(user_id=user_id, memory_type=memory_type).all()
    for item in existing_items:
        if item.content == content:
            continue
        await _record_memory_event(
            user_id=user_id,
            memory_type=memory_type,
            action="replaced",
            old_content=item.content,
            new_content=content,
            note="新记忆覆盖旧记忆",
        )
        await MemoryMeta.filter(memory=item).delete()
        await item.delete()


async def remember_user_facts(user_id: str, text: str, source_message_id=None) -> int:
    try:
        facts = await extract_long_term_facts(text, use_llm=True)
        if not facts:
            return 0

        embeddings_model = get_embeddings_model()
        created_count = 0

        for fact in facts:
            memory_type = str(fact["memory_type"])
            content = str(fact["content"])
            confidence = float(fact.get("confidence", 0.8))
            source = str(fact.get("source", "regex"))

            await _resolve_conflicts(user_id=user_id, memory_type=memory_type, content=content)

            exists = await LongMemory.filter(
                user_id=user_id,
                memory_type=memory_type,
                content=content,
            ).exists()
            if exists:
                memory = await LongMemory.get(user_id=user_id, memory_type=memory_type, content=content)
                await _ensure_memory_meta(memory, confidence, source)
                continue

            try:
                embedding = embeddings_model.embed_query(content)
            except Exception:
                embedding = None

            memory = await LongMemory.create(
                user_id=user_id,
                memory_type=memory_type,
                content=content,
                source_message_id=source_message_id,
                embedding=embedding,
            )
            await _ensure_memory_meta(memory, confidence, source)
            await _record_memory_event(
                user_id=user_id,
                memory_type=memory_type,
                action="created",
                new_content=content,
                note=source,
            )
            created_count += 1

        return created_count
    except Exception:
        return 0


async def search_long_memory(
    user_id: str,
    query: str,
    top_k: int = 3,
    min_score: float = 0.1,
) -> list[str]:
    memories = await LongMemory.filter(user_id=user_id).all()
    if not memories:
        return []

    meta_map = {
        str(meta.memory_id): meta
        for meta in await MemoryMeta.filter(memory__user_id=user_id)
    }

    try:
        embeddings_model = get_embeddings_model()
        query_embedding = embeddings_model.embed_query(query)
    except Exception:
        query_embedding = []

    query_keywords = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9_]+", query.lower())
    scored: list[tuple[float, LongMemory]] = []

    for memory in memories:
        score = 0.0
        if query_embedding and memory.embedding:
            score += _cosine_similarity(query_embedding, memory.embedding) * 0.7
        lowered = memory.content.lower()
        keyword_hits = sum(lowered.count(keyword) for keyword in query_keywords if len(keyword) > 1)
        score += keyword_hits * 0.08

        meta = meta_map.get(str(memory.memory_id))
        if meta:
            score += meta.confidence * 0.12
            if meta.confirmed:
                score += 0.15
        score += min(memory.hit_count, 20) * 0.01

        if score >= min_score:
            scored.append((score, memory))

    if not scored:
        recent_items = await LongMemory.filter(user_id=user_id).order_by("-created_time").limit(top_k)
        return [item.content for item in recent_items]

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = scored[:top_k]

    for _, memory in selected:
        memory.hit_count += 1
        await memory.save()

    return [memory.content for _, memory in selected]
