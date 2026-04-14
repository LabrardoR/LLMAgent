from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.core.security import get_current_user
from app.core.storage import resolve_data_path
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_document_meta import KnowledgeDocumentMeta
from app.models.user import User
from app.rag.service import (
    build_rag_payload,
    delete_document_assets,
    get_document_storage_info,
    rebuild_user_vector_index,
    save_uploaded_document,
)
from app.schemas.knowledge import KnowledgeDocumentOut, KnowledgeSearchRequest

router = APIRouter()


def _document_urls(document_id: str) -> dict[str, str]:
    return {
        "download_url": f"/api/knowledge/documents/{document_id}/download",
        "preview_url": f"/api/knowledge/documents/{document_id}/content",
    }


async def _build_document_out(document: KnowledgeDocument) -> KnowledgeDocumentOut:
    meta = await KnowledgeDocumentMeta.get_or_none(document=document)
    storage_info = get_document_storage_info(document)
    return KnowledgeDocumentOut(
        document_id=document.document_id,
        title=document.title,
        file_name=document.file_name,
        chunk_count=document.chunk_count,
        status=document.status,
        storage_location=storage_info["storage_location"],
        file_size=storage_info["file_size"],
        content_type=storage_info["content_type"],
        asset_url=storage_info["asset_url"],
        download_url=_document_urls(str(document.document_id))["download_url"],
        preview_url=_document_urls(str(document.document_id))["preview_url"],
        group_name=meta.group_name if meta else "",
        tags=meta.tags if meta else [],
        description=meta.description if meta else "",
        created_time=document.created_time,
    )


async def _get_user_document(document_id: str, current_user: User) -> KnowledgeDocument:
    document = await KnowledgeDocument.get_or_none(document_id=document_id, user=current_user)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")
    return document


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
    document = await _get_user_document(document_id, current_user)
    return await _build_document_out(document)


@router.get("/documents/{document_id}/content", summary="预览文档内容")
async def preview_document_content(
    document_id: str,
    max_chars: int = Query(4000, ge=200, le=20000),
    current_user: User = Depends(get_current_user),
):
    document = await _get_user_document(document_id, current_user)
    storage_info = get_document_storage_info(document)
    return {
        "document_id": str(document.document_id),
        "title": document.title,
        "file_name": document.file_name,
        "content_type": storage_info["content_type"],
        "storage_location": storage_info["storage_location"],
        "content_length": len(document.content or ""),
        "truncated": len(document.content or "") > max_chars,
        "content": (document.content or "")[:max_chars],
    }


@router.get("/documents/{document_id}/download", summary="下载原始文档")
async def download_document(document_id: str, current_user: User = Depends(get_current_user)):
    document = await _get_user_document(document_id, current_user)
    try:
        file_path = resolve_data_path(document.file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="文档存储路径无效") from exc

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="文档原文件不存在")

    storage_info = get_document_storage_info(document)
    return FileResponse(
        path=file_path,
        filename=document.file_name,
        media_type=storage_info["content_type"],
    )


@router.get("/documents/{document_id}/chunks", summary="获取文档分片")
async def get_document_chunks(document_id: str, current_user: User = Depends(get_current_user)):
    document = await _get_user_document(document_id, current_user)
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


@router.get("/stats", summary="获取知识库统计信息")
async def knowledge_stats(current_user: User = Depends(get_current_user)):
    documents = await KnowledgeDocument.filter(user=current_user)
    meta_records = await KnowledgeDocumentMeta.filter(document_id__in=[doc.document_id for doc in documents])

    total_size = 0
    status_counts: dict[str, int] = {}
    group_names: set[str] = set()
    tag_names: set[str] = set()

    for document in documents:
        info = get_document_storage_info(document)
        total_size += info["file_size"]
        status_counts[document.status] = status_counts.get(document.status, 0) + 1

    for meta in meta_records:
        if meta.group_name:
            group_names.add(meta.group_name)
        for tag in meta.tags or []:
            tag_names.add(tag)

    return {
        "document_count": len(documents),
        "chunk_count": sum(item.chunk_count for item in documents),
        "total_size_bytes": total_size,
        "status_counts": status_counts,
        "group_count": len(group_names),
        "tag_count": len(tag_names),
    }


@router.post("/rebuild-index", summary="重建当前用户向量索引")
async def rebuild_index(current_user: User = Depends(get_current_user)):
    chunk_count = await rebuild_user_vector_index(str(current_user.user_id))
    return {"message": "向量索引已重建", "chunk_count": chunk_count}


@router.delete("/documents/{document_id}", summary="删除知识库文档")
async def delete_document(document_id: str, current_user: User = Depends(get_current_user)):
    document = await _get_user_document(document_id, current_user)
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
