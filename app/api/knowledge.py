"""
知识库 API。

提供：
1. 上传并建立索引；
2. 文档列表、详情、分组管理；
3. 删除文档并同步清理索引；
4. 结构化检索结果，方便前端展示引用来源。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.core.security import get_current_user
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_document_meta import KnowledgeDocumentMeta
from app.models.user import User
from app.rag.service import (
    build_rag_payload,
    delete_document_assets,
    save_uploaded_document,
)
from app.schemas.knowledge import KnowledgeDocumentOut, KnowledgeSearchRequest

router = APIRouter()


async def _build_document_out(document: KnowledgeDocument) -> KnowledgeDocumentOut:
    meta = await KnowledgeDocumentMeta.get_or_none(document=document)
    return KnowledgeDocumentOut(
        document_id=document.document_id,
        title=document.title,
        file_name=document.file_name,
        chunk_count=document.chunk_count,
        status=document.status,
        group_name=meta.group_name if meta else "",
        tags=meta.tags if meta else [],
        description=meta.description if meta else "",
        created_time=document.created_time,
    )


@router.post("/documents/upload", response_model=KnowledgeDocumentOut, summary="上传知识库文档")
async def upload_document(
    file: UploadFile = File(...),
    group_name: str = Form(""),
    tags: str = Form(""),
    description: str = Form(""),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空文件")

    try:
        document = await save_uploaded_document(
            user_id=str(current_user.user_id),
            file_name=file.filename or "document.txt",
            content=content,
            group_name=group_name,
            tags=tags,
            description=description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await _build_document_out(document)


@router.get("/documents", response_model=list[KnowledgeDocumentOut], summary="获取我的知识库文档")
async def list_documents(
    group_name: str | None = None,
    tag: str | None = None,
    current_user: User = Depends(get_current_user),
):
    documents = await KnowledgeDocument.filter(user=current_user).order_by("-created_time")
    items: list[KnowledgeDocumentOut] = []

    for document in documents:
        item = await _build_document_out(document)
        if group_name and item.group_name != group_name:
            continue
        if tag and tag not in item.tags:
            continue
        items.append(item)
    return items


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentOut, summary="获取知识库文档详情")
async def get_document(document_id: str, current_user: User = Depends(get_current_user)):
    document = await KnowledgeDocument.get_or_none(document_id=document_id, user=current_user)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")
    return await _build_document_out(document)


@router.get("/documents/{document_id}/chunks", summary="获取文档分片")
async def get_document_chunks(document_id: str, current_user: User = Depends(get_current_user)):
    document = await KnowledgeDocument.get_or_none(document_id=document_id, user=current_user)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")

    chunks = await KnowledgeChunk.filter(document=document).order_by("chunk_index")
    return [
        {
            "chunk_id": str(item.chunk_id),
            "chunk_index": item.chunk_index,
            "content": item.content,
            "vector_id": item.vector_id,
        }
        for item in chunks
    ]


@router.get("/groups", summary="获取知识库分组和标签概览")
async def get_groups(current_user: User = Depends(get_current_user)):
    documents = await KnowledgeDocument.filter(user=current_user)
    document_ids = [doc.document_id for doc in documents]
    meta_records = await KnowledgeDocumentMeta.filter(document_id__in=document_ids)

    groups: dict[str, int] = {}
    tags: dict[str, int] = {}
    for item in meta_records:
        if item.group_name:
            groups[item.group_name] = groups.get(item.group_name, 0) + 1
        for tag in item.tags or []:
            tags[tag] = tags.get(tag, 0) + 1

    return {
        "groups": [{"name": name, "count": count} for name, count in sorted(groups.items())],
        "tags": [{"name": name, "count": count} for name, count in sorted(tags.items())],
    }


@router.delete("/documents/{document_id}", summary="删除知识库文档")
async def delete_document(document_id: str, current_user: User = Depends(get_current_user)):
    document = await KnowledgeDocument.get_or_none(document_id=document_id, user=current_user)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")
    await delete_document_assets(document)
    return {"message": "文档已删除"}


@router.post("/search", summary="知识库检索")
async def search_documents(payload: KnowledgeSearchRequest, current_user: User = Depends(get_current_user)):
    result = await build_rag_payload(
        user_id=str(current_user.user_id),
        query=payload.query,
        top_k=payload.top_k,
        group_name=payload.group_name,
        tag=payload.tag,
    )
    return result
