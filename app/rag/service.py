"""
RAG 业务服务层。

负责把“上传文件 -> 切分 -> 向量化 -> 索引持久化 -> 检索拼接上下文”
串成完整链路，供 API 与聊天流程复用。
"""

import uuid
from pathlib import Path

from langchain_core.documents import Document

from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_chunk import KnowledgeChunk
from app.rag.loader import load_text_from_file, split_text_content
from app.rag.vector_store import vector_store_manager


UPLOAD_ROOT = Path("app/data/uploads")


def _user_upload_dir(user_id: str) -> Path:
    """返回用户上传目录，不存在时自动创建。"""
    path = UPLOAD_ROOT / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_uploaded_document(user_id: str, file_name: str, content: bytes) -> KnowledgeDocument:
    """
    保存并索引用户上传文档。

    流程：
    1) 文件落盘；
    2) 文本读取与切分；
    3) 写入向量库；
    4) 建立 chunk 元数据与向量 ID 映射；
    5) 更新文档状态为 indexed。
    """
    document = None
    try:
        ext = Path(file_name).suffix.lower()
        unique_name = f"{uuid.uuid4().hex}{ext}"
        save_path = _user_upload_dir(user_id) / unique_name

        # 安全地写入文件
        try:
            save_path.write_bytes(content)
        except Exception as e:
            raise ValueError(f"文件保存失败: {str(e)}")

        # 读取和解析文本
        try:
            text = load_text_from_file(str(save_path))
        except ValueError as e:
            # 清理已保存的文件
            if save_path.exists():
                save_path.unlink()
            raise e
        except Exception as e:
            if save_path.exists():
                save_path.unlink()
            raise ValueError(f"文件解析失败: {str(e)}")

        if not text or not text.strip():
            if save_path.exists():
                save_path.unlink()
            raise ValueError("文件内容为空")

        # 创建文档记录
        document = await KnowledgeDocument.create(
            user_id=user_id,
            title=Path(file_name).stem,
            file_name=file_name,
            file_path=str(save_path).replace("\\", "/"),
            content=text,
            status="processing"
        )

        metadata = {"user_id": user_id, "document_id": str(document.document_id), "title": document.title}

        # 切分文档
        try:
            chunks = split_text_content(text, metadata=metadata)
        except Exception as e:
            document.status = "failed"
            await document.save()
            raise ValueError(f"文档切分失败: {str(e)}")

        if not chunks:
            document.status = "failed"
            await document.save()
            raise ValueError("文档切分后无有效内容")

        for idx, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = idx

        # 写入向量库
        try:
            vector_ids = vector_store_manager.add_documents(user_id=user_id, docs=chunks)
        except Exception as e:
            document.status = "failed"
            await document.save()
            raise ValueError(f"向量索引构建失败: {str(e)}")

        # 创建chunk记录
        try:
            for idx, chunk in enumerate(chunks):
                await KnowledgeChunk.create(
                    document_id=document.document_id,
                    chunk_index=idx,
                    content=chunk.page_content,
                    vector_id=(vector_ids[idx] if idx < len(vector_ids) else None),
                )
        except Exception as e:
            document.status = "failed"
            await document.save()
            raise ValueError(f"Chunk记录创建失败: {str(e)}")

        # 更新文档状态
        document.chunk_count = len(chunks)
        document.status = "indexed"
        await document.save()

        return document

    except Exception as e:
        # 确保异常被正确传播
        if isinstance(e, ValueError):
            raise e
        raise ValueError(f"文档处理失败: {str(e)}")


async def search_user_knowledge(user_id: str, query: str, top_k: int = 4) -> list[Document]:
    """对指定用户知识库执行向量检索。"""
    try:
        return vector_store_manager.similarity_search(user_id=user_id, query=query, top_k=top_k)
    except Exception as e:
        # 检索失败时返回空列表而不是抛出异常，保证聊天流程不中断
        print(f"Knowledge search error for user {user_id}: {e}")
        return []


async def build_rag_context(user_id: str, query: str, top_k: int = 4) -> str:
    """
    将检索结果拼接为可直接注入 Prompt 的上下文文本。

    格式中包含序号与文档标题，便于模型生成时引用来源。
    """
    try:
        docs = await search_user_knowledge(user_id=user_id, query=query, top_k=top_k)
        if not docs:
            return ""
        lines = []
        for idx, item in enumerate(docs, 1):
            title = item.metadata.get("title", "未命名文档")
            lines.append(f"[{idx}] {title}: {item.page_content}")
        return "\n".join(lines)
    except Exception as e:
        print(f"RAG context build error: {e}")
        return ""
