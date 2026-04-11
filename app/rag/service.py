"""
RAG 业务服务层。

负责把“上传文件 -> 切分 -> 向量化 -> 检索 -> 引用整理”串成完整链路。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_document_meta import KnowledgeDocumentMeta
from app.rag.loader import load_text_from_file, split_text_content
from app.rag.vector_store import vector_store_manager

UPLOAD_ROOT = Path("app/data/uploads")


def _user_upload_dir(user_id: str) -> Path:
    path = UPLOAD_ROOT / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_tags(raw_tags: str | None) -> list[str]:
    if not raw_tags:
        return []
    tags = [item.strip() for item in raw_tags.split(",")]
    return [item for item in tags if item]


def _extract_keywords(query: str) -> list[str]:
    keywords = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9_]+", query.lower())
    unique: list[str] = []
    for item in keywords:
        if item not in unique and len(item) > 1:
            unique.append(item)
    return unique[:10]


def _count_keyword_hits(text: str, keywords: list[str]) -> int:
    lowered = text.lower()
    return sum(lowered.count(keyword) for keyword in keywords)


def _build_highlight_snippet(text: str, keywords: list[str], limit: int = 220) -> str:
    content = text.strip().replace("\n", " ")
    if not content:
        return ""

    start = 0
    lowered = content.lower()
    for keyword in keywords:
        index = lowered.find(keyword.lower())
        if index >= 0:
            start = max(0, index - 40)
            break

    snippet = content[start:start + limit]
    for keyword in keywords:
        snippet = re.sub(
            re.escape(keyword),
            lambda match: f"**{match.group(0)}**",
            snippet,
            flags=re.IGNORECASE,
        )
    return snippet


async def save_uploaded_document(
    user_id: str,
    file_name: str,
    content: bytes,
    group_name: str = "",
    tags: str | None = None,
    description: str = "",
) -> KnowledgeDocument:
    document: KnowledgeDocument | None = None
    save_path: Path | None = None

    try:
        ext = Path(file_name).suffix.lower()
        unique_name = f"{uuid.uuid4().hex}{ext}"
        save_path = _user_upload_dir(user_id) / unique_name
        save_path.write_bytes(content)

        text = load_text_from_file(str(save_path))
        if not text or not text.strip():
            raise ValueError("文件内容为空")

        document = await KnowledgeDocument.create(
            user_id=user_id,
            title=Path(file_name).stem,
            file_name=file_name,
            file_path=str(save_path).replace("\\", "/"),
            content=text,
            status="processing",
        )
        await KnowledgeDocumentMeta.create(
            document=document,
            group_name=group_name.strip(),
            tags=_parse_tags(tags),
            description=description.strip(),
        )

        metadata = {
            "user_id": user_id,
            "document_id": str(document.document_id),
            "title": document.title,
            "group_name": group_name.strip(),
            "tags": _parse_tags(tags),
        }
        chunks = split_text_content(text, metadata=metadata)
        if not chunks:
            raise ValueError("文档切分后无有效内容")

        for index, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = index

        vector_ids = vector_store_manager.add_documents(user_id=user_id, docs=chunks)

        for index, chunk in enumerate(chunks):
            await KnowledgeChunk.create(
                document_id=document.document_id,
                chunk_index=index,
                content=chunk.page_content,
                vector_id=vector_ids[index] if index < len(vector_ids) else None,
            )

        document.chunk_count = len(chunks)
        document.status = "indexed"
        await document.save()
        return document
    except ValueError:
        if document:
            document.status = "failed"
            await document.save()
        if save_path and save_path.exists():
            save_path.unlink()
        raise
    except Exception as exc:
        if document:
            document.status = "failed"
            await document.save()
        if save_path and save_path.exists():
            save_path.unlink()
        raise ValueError(f"文档处理失败: {exc}") from exc


async def rebuild_user_vector_index(user_id: str) -> int:
    chunks = await KnowledgeChunk.filter(document__user_id=user_id).select_related("document").order_by("document_id", "chunk_index")
    docs: list[Document] = []
    chunk_ids: list[str] = []

    for chunk in chunks:
        meta_record = await KnowledgeDocumentMeta.get_or_none(document_id=chunk.document_id)
        docs.append(
            Document(
                page_content=chunk.content,
                metadata={
                    "user_id": user_id,
                    "document_id": str(chunk.document_id),
                    "title": chunk.document.title,
                    "chunk_index": chunk.chunk_index,
                    "group_name": meta_record.group_name if meta_record else "",
                    "tags": meta_record.tags if meta_record else [],
                },
            )
        )
        chunk_ids.append(str(chunk.chunk_id))

    vector_ids = vector_store_manager.replace_documents(user_id=user_id, docs=docs)
    for index, chunk_id in enumerate(chunk_ids):
        vector_id = vector_ids[index] if index < len(vector_ids) else None
        await KnowledgeChunk.filter(chunk_id=chunk_id).update(vector_id=vector_id)
    return len(vector_ids)


async def delete_document_assets(document: KnowledgeDocument) -> None:
    user_id = str(document.user_id)

    if document.file_path:
        file_path = Path(document.file_path)
        if file_path.exists() and file_path.is_file():
            file_path.unlink()

    await KnowledgeChunk.filter(document=document).delete()
    await KnowledgeDocumentMeta.filter(document=document).delete()
    await document.delete()
    await rebuild_user_vector_index(user_id)


async def get_document_meta_map(document_ids: list[str]) -> dict[str, KnowledgeDocumentMeta]:
    if not document_ids:
        return {}
    meta_records = await KnowledgeDocumentMeta.filter(document_id__in=document_ids)
    return {str(item.document_id): item for item in meta_records}


async def search_user_knowledge(
    user_id: str,
    query: str,
    top_k: int = 4,
    group_name: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """
    混合检索：
    1. 先用向量检索拿候选；
    2. 再用关键词命中数做简单 rerank；
    3. 返回结构化引用信息，方便前端展示。
    """
    keywords = _extract_keywords(query)
    document_filter_ids: set[str] | None = None

    if group_name or tag:
        meta_query = KnowledgeDocumentMeta.all()
        if group_name:
            meta_query = meta_query.filter(group_name=group_name)
        meta_records = await meta_query
        if tag:
            meta_records = [item for item in meta_records if tag in (item.tags or [])]
        document_filter_ids = {str(item.document_id) for item in meta_records}
        if not document_filter_ids:
            return []

    candidates: dict[str, dict[str, Any]] = {}

    vector_hits = vector_store_manager.similarity_search_with_score(user_id=user_id, query=query, top_k=max(top_k * 3, 6))
    for doc, raw_score in vector_hits:
        document_id = str(doc.metadata.get("document_id", ""))
        if document_filter_ids is not None and document_id not in document_filter_ids:
            continue
        content = doc.page_content
        keyword_hits = _count_keyword_hits(content, keywords)
        distance_score = 1.0 / (1.0 + float(raw_score))
        final_score = distance_score + keyword_hits * 0.15
        key = f"{document_id}:{doc.metadata.get('chunk_index', 0)}"
        candidates[key] = {
            "document_id": document_id,
            "title": doc.metadata.get("title", "未命名文档"),
            "content": content,
            "chunk_index": int(doc.metadata.get("chunk_index", 0)),
            "score": final_score,
            "group_name": doc.metadata.get("group_name", ""),
            "tags": doc.metadata.get("tags", []),
        }

    if keywords:
        chunk_query = KnowledgeChunk.filter(document__user_id=user_id).select_related("document")
        if document_filter_ids is not None:
            chunk_query = chunk_query.filter(document_id__in=document_filter_ids)
        for chunk in await chunk_query:
            keyword_hits = _count_keyword_hits(chunk.content, keywords)
            if keyword_hits <= 0:
                continue
            key = f"{chunk.document_id}:{chunk.chunk_index}"
            item = candidates.get(key)
            if item:
                item["score"] += keyword_hits * 0.2
                continue
            candidates[key] = {
                "document_id": str(chunk.document_id),
                "title": chunk.document.title,
                "content": chunk.content,
                "chunk_index": chunk.chunk_index,
                "score": keyword_hits * 0.2,
                "group_name": "",
                "tags": [],
            }

    if not candidates:
        return []

    document_ids = [item["document_id"] for item in candidates.values()]
    meta_map = await get_document_meta_map(document_ids)

    results = sorted(candidates.values(), key=lambda item: item["score"], reverse=True)[:top_k]
    items: list[dict[str, Any]] = []
    for item in results:
        meta_record = meta_map.get(item["document_id"])
        tags = item["tags"] or (meta_record.tags if meta_record else [])
        group_value = item["group_name"] or (meta_record.group_name if meta_record else "")
        snippet = _build_highlight_snippet(item["content"], keywords)
        items.append(
            {
                "document_id": item["document_id"],
                "title": item["title"],
                "chunk_index": item["chunk_index"],
                "score": round(float(item["score"]), 4),
                "snippet": snippet,
                "content": item["content"],
                "group_name": group_value,
                "tags": tags,
            }
        )
    return items


async def build_rag_payload(
    user_id: str,
    query: str,
    top_k: int = 4,
    group_name: str | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    items = await search_user_knowledge(
        user_id=user_id,
        query=query,
        top_k=top_k,
        group_name=group_name,
        tag=tag,
    )
    context_lines = [
        f"[{index}] {item['title']} (chunk {item['chunk_index']}): {item['content']}"
        for index, item in enumerate(items, 1)
    ]
    return {
        "context": "\n".join(context_lines),
        "references": [
            {
                "index": index,
                "document_id": item["document_id"],
                "title": item["title"],
                "chunk_index": item["chunk_index"],
                "snippet": item["snippet"],
                "group_name": item["group_name"],
                "tags": item["tags"],
                "score": item["score"],
            }
            for index, item in enumerate(items, 1)
        ],
        "items": items,
    }


async def build_rag_context(user_id: str, query: str, top_k: int = 4) -> str:
    payload = await build_rag_payload(user_id=user_id, query=query, top_k=top_k)
    return str(payload["context"])
