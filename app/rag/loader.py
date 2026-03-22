"""
RAG 文档预处理模块。

职责：
1) 读取上传后的文本类文件；
2) 进行基础格式规范化（如 JSON 美化）；
3) 将长文本切分为可用于向量化检索的分片。
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

import json
from pathlib import Path

TEXT_FILE_SUFFIXES = {".txt", ".md", ".csv", ".json", ".log"}


def load_text_from_file(file_path: str) -> str:
    """
    从文件中读取文本内容。

    - 限定为文本类后缀，避免将二进制文件误当文本读取；
    - JSON 文件会优先尝试解析并规范化，提升后续切分与检索质量。
    """
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix not in TEXT_FILE_SUFFIXES:
        raise ValueError("仅支持 txt/md/csv/json/log 文本文件")
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".json":
        try:
            obj = json.loads(raw)
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            return raw
    return raw


def split_text_content(
    content: str,
    metadata: dict,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
) -> list[Document]:
    """
    将文本切分为 Document 列表并携带统一元数据。

    参数：
    - chunk_size: 每个分片目标长度；
    - chunk_overlap: 相邻分片重叠长度，用于降低语义断裂。
    """
    if not content.strip():
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap
    )
    return splitter.create_documents([content], metadatas=[metadata])
