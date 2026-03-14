"""
知识库 API。

提供用户级知识库管理能力：
1) 上传并构建索引；
2) 文档列表查询；
3) 文档删除；
4) 检索上下文预览。
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.security import get_current_user
from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.user import User
from app.rag.service import build_rag_context, save_uploaded_document
from app.schemas.knowledge import KnowledgeDocumentOut, KnowledgeSearchRequest

router = APIRouter()


@router.post("/documents/upload", response_model=KnowledgeDocumentOut, summary="上传知识库文档")
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传文档并触发 RAG 索引构建。"""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空文件")
    try:
        document = await save_uploaded_document(str(current_user.user_id), file.filename or "document.txt", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return document


@router.get("/documents", response_model=list[KnowledgeDocumentOut], summary="获取我的知识库文档")
async def list_documents(current_user: User = Depends(get_current_user)):
    """获取当前用户上传的全部知识库文档。"""
    return await KnowledgeDocument.filter(user=current_user).order_by("-created_time")


@router.delete("/documents/{document_id}", summary="删除知识库文档")
async def delete_document(document_id: str, current_user: User = Depends(get_current_user)):
    """删除文档及其分片元数据。"""
    document = await KnowledgeDocument.get_or_none(document_id=document_id, user=current_user)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")
    await KnowledgeChunk.filter(document=document).delete()
    await document.delete()
    return {"message": "文档已删除"}


@router.post("/search", summary="知识库向量检索")
async def search_documents(payload: KnowledgeSearchRequest, current_user: User = Depends(get_current_user)):
    """执行检索并返回可读上下文，便于调试与前端展示。"""
    context = await build_rag_context(str(current_user.user_id), payload.query, payload.top_k)
    return {"context": context}
