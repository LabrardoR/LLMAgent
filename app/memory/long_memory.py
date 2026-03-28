"""
长期记忆模块。

核心流程：
1) 从用户输入中抽取结构化事实；
2) 持久化到 LongMemory 表并生成 embedding；
3) 在新问题到来时按向量相似度召回相关记忆。
"""

import math
import re
import json
import os

from app.models.long_memory import LongMemory
from app.rag.vector_store import get_embeddings_model


# 基础正则模式（快速路径）
_name_pattern = re.compile(r"(?:我叫|我的名字是|我是|叫我)([^\s，。！？]{1,20})")
_city_pattern = re.compile(r"(?:我来自|我住在|我在|我的城市是)([^\s，。！？]{1,20})(?:工作|生活|居住|市)?")
_job_pattern = re.compile(r"(?:我是|我的职业是|我从事|我做|我在做|我是一名)([^\s，。！？]{1,20})(?:工作|职业|岗位)?")
_hobby_pattern = re.compile(r"(?:我喜欢|我爱好是|我喜欢的是|我的爱好是|我平时喜欢)([^\s，。！？]{1,50})")
_age_pattern = re.compile(r"(?:我今年|我)(\d{1,3})(?:岁|周岁)")
_skill_pattern = re.compile(r"(?:我会|我擅长|我精通|我熟悉)([^\s，。！？]{1,50})")
_dislike_pattern = re.compile(r"(?:我不喜欢|我讨厌|我不爱)([^\s，。！？]{1,50})")
_language_pattern = re.compile(r"(?:我会说|我会|我掌握)([^\s，。！？]{1,20})(?:语|话)")
_project_pattern = re.compile(r"(?:我在做|我正在做|我的项目是)([^\s，。！？]{1,50})(?:项目|课题)?")
_education_pattern = re.compile(r"(?:我毕业于|我在|我就读于)([^\s，。！？]{1,30})(?:大学|学院|学校)")


def extract_long_term_facts_with_regex(text: str) -> list[tuple[str, str]]:
    """
    使用正则表达式从自然语言中抽取可沉淀的长期事实（快速路径）。

    返回值为 (memory_type, memory_content) 的列表。
    """
    facts: list[tuple[str, str]] = []
    patterns = [
        (_name_pattern, "name", "用户姓名是{value}"),
        (_city_pattern, "city", "用户所在城市是{value}"),
        (_job_pattern, "job", "用户职业是{value}"),
        (_hobby_pattern, "hobby", "用户的爱好是{value}"),
        (_age_pattern, "age", "用户年龄是{value}岁"),
        (_skill_pattern, "skill", "用户擅长{value}"),
        (_dislike_pattern, "dislike", "用户不喜欢{value}"),
        (_language_pattern, "language", "用户会说{value}"),
        (_project_pattern, "project", "用户的项目是{value}"),
        (_education_pattern, "education", "用户毕业于{value}"),
    ]

    for pattern, memory_type, template in patterns:
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            if value:  # 确保值不为空
                facts.append((memory_type, template.format(value=value)))

    return facts


async def extract_long_term_facts_with_llm(text: str) -> list[tuple[str, str]]:
    """
    使用LLM从文本中提取长期记忆事实（准确但较慢）。

    仅在正则提取失败时使用。
    """
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

        prompt = f"""从以下用户输入中提取长期记忆信息。只提取明确的个人信息。

用户输入: {text}

请以JSON格式返回提取的信息，格式如下：
{{
  "name": "姓名（如果提到）",
  "city": "城市（如果提到）",
  "job": "职业（如果提到）",
  "hobby": "爱好（如果提到）",
  "age": "年龄（如果提到，仅数字）",
  "skill": "技能/擅长（如果提到）",
  "dislike": "不喜欢的事物（如果提到）",
  "language": "语言能力（如果提到）",
  "project": "项目/课题（如果提到）",
  "education": "教育背景（如果提到）",
  "other": ["其他重要的个人信息"]
}}

如果没有提取到任何信息，返回空对象 {{}}。
只返回JSON，不要其他解释。"""

        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, 'content') else str(response)

        # 尝试解析JSON
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        data = json.loads(content)
        facts = []

        templates = {
            "name": ("name", "用户姓名是{value}"),
            "city": ("city", "用户所在城市是{value}"),
            "job": ("job", "用户职业是{value}"),
            "hobby": ("hobby", "用户的爱好是{value}"),
            "age": ("age", "用户年龄是{value}岁"),
            "skill": ("skill", "用户擅长{value}"),
            "dislike": ("dislike", "用户不喜欢{value}"),
            "language": ("language", "用户会说{value}"),
            "project": ("project", "用户的项目是{value}"),
            "education": ("education", "用户毕业于{value}"),
        }

        for key, (mem_type, template) in templates.items():
            value = data.get(key)
            if value and str(value).strip():
                facts.append((mem_type, template.format(value=value)))

        # 处理其他信息
        others = data.get("other", [])
        if isinstance(others, list):
            for item in others:
                if item and str(item).strip():
                    facts.append(("other", str(item)))

        return facts

    except Exception as e:
        print(f"LLM extraction failed: {e}")
        return []


async def extract_long_term_facts(text: str, use_llm: bool = True) -> list[tuple[str, str]]:
    """
    从自然语言中抽取可沉淀的长期事实。

    策略：
    1. 优先使用正则表达式快速提取（速度快）；
    2. 如果正则未提取到内容且启用LLM，则使用LLM提取（更准确）。

    参数：
    - text: 待提取的文本
    - use_llm: 是否启用LLM提取（默认True）

    返回：(memory_type, content) 的列表
    """
    # 优先使用正则快速提取
    facts = extract_long_term_facts_with_regex(text)

    # 如果正则没有提取到任何内容，且启用了LLM提取，则使用LLM
    if not facts and use_llm:
        try:
            facts = await extract_long_term_facts_with_llm(text)
        except Exception as e:
            print(f"LLM extraction failed, falling back to regex: {e}")

    return facts


async def remember_user_facts(user_id: str, text: str, source_message_id=None) -> int:
    """
    将抽取到的事实写入长期记忆库。

    - 自动去重：同一用户、同类型、同内容不重复写入；
    - 返回本次新增的记忆条数。
    """
    try:
        # 使用异步的extract_long_term_facts
        facts = await extract_long_term_facts(text, use_llm=True)
        if not facts:
            return 0

        try:
            embeddings_model = get_embeddings_model()
        except Exception as e:
            print(f"Failed to get embeddings model: {e}")
            return 0

        created = 0
        for memory_type, content in facts:
            try:
                exists = await LongMemory.filter(user_id=user_id, memory_type=memory_type, content=content).exists()
                if exists:
                    print(f"Memory already exists: {memory_type} - {content}")
                    continue

                try:
                    embedding = embeddings_model.embed_query(content)
                except Exception as e:
                    print(f"Failed to generate embedding: {e}")
                    # 即使embedding失败，也保存记忆（embedding可以为null）
                    embedding = None

                await LongMemory.create(
                    user_id=user_id,
                    memory_type=memory_type,
                    content=content,
                    source_message_id=source_message_id,
                    embedding=embedding
                )
                created += 1
                print(f"✓ Created long-term memory: {memory_type} - {content}")
            except Exception as e:
                print(f"Failed to create memory: {e}")
                continue

        if created > 0:
            print(f"📝 Successfully created {created} new long-term memories for user {user_id}")

        return created
    except Exception as e:
        print(f"Error in remember_user_facts: {e}")
        return 0


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    numerator = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return numerator / (norm1 * norm2)


async def search_long_memory(user_id: str, query: str, top_k: int = 3, min_score: float = 0.1) -> list[str]:
    """
    按语义相关性召回长期记忆文本。

    召回后会更新 hit_count，用于后续统计与优化。

    参数：
    - user_id: 用户ID
    - query: 查询文本
    - top_k: 返回的最大记忆数量
    - min_score: 最小相似度阈值（0-1），低于此值的记忆不会被返回

    返回：相关的记忆内容列表
    """
    try:
        memories = await LongMemory.filter(user_id=user_id).all()
        if not memories:
            print(f"No long-term memories found for user {user_id}")
            return []

        print(f"Found {len(memories)} long-term memories for user {user_id}")

        try:
            embeddings_model = get_embeddings_model()
            query_embedding = embeddings_model.embed_query(query)
        except Exception as e:
            print(f"Failed to generate query embedding: {e}")
            # embedding失败时，返回最近的记忆
            recent_memories = sorted(memories, key=lambda m: m.created_time, reverse=True)[:top_k]
            return [m.content for m in recent_memories]

        scored = []
        for memory in memories:
            try:
                # 如果memory没有embedding，跳过相似度计算
                if not memory.embedding:
                    continue
                score = _cosine_similarity(query_embedding, memory.embedding)
                scored.append((score, memory))
            except Exception as e:
                print(f"Failed to calculate similarity: {e}")
                continue

        if not scored:
            # 如果没有可计算的记忆，返回最近的
            recent_memories = sorted(memories, key=lambda m: m.created_time, reverse=True)[:top_k]
            print(f"No memories with embeddings, returning {len(recent_memories)} recent memories")
            return [m.content for m in recent_memories]

        # 按相似度排序
        scored.sort(key=lambda item: item[0], reverse=True)

        # 过滤掉相似度过低的记忆
        filtered = [(score, mem) for score, mem in scored if score >= min_score]

        if not filtered:
            print(f"No memories with score >= {min_score}")
            return []

        # 取top_k
        selected = filtered[:top_k]

        # 更新hit_count
        for score, memory in selected:
            try:
                memory.hit_count += 1
                await memory.save()
            except Exception as e:
                print(f"Failed to update hit_count: {e}")

        result = [mem.content for score, mem in selected]
        print(f"🔍 Recalled {len(result)} long-term memories (scores: {[f'{score:.3f}' for score, _ in selected]})")

        return result
    except Exception as e:
        print(f"Error in search_long_memory: {e}")
        return []
