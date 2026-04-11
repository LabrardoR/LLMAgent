"""
向量存储模块。

设计目标：
1. 使用用户级目录隔离 FAISS 索引；
2. 优先使用 DashScope Embedding；
3. 在无在线 embedding 服务时提供本地兜底；
4. 支持索引重建和删除，方便知识库维护。
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
from typing import Any

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings


class HashEmbeddings(Embeddings):
    def __init__(self, size: int = 128):
        self.size = size

    def _encode(self, text: str) -> list[float]:
        vector = [0.0] * self.size
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            index = int(digest[:8], 16) % self.size
            vector[index] += 1.0
        norm = math.sqrt(sum(item * item for item in vector)) or 1.0
        return [item / norm for item in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._encode(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._encode(text)


def get_embeddings_model() -> Embeddings:
    dashscope_api_key = os.getenv("DASHSCOPE_API_KEY")
    if dashscope_api_key:
        try:
            return DashScopeEmbeddings(
                model="text-embedding-v2",
                dashscope_api_key=dashscope_api_key,
            )
        except Exception:
            pass
    return HashEmbeddings()


class UserVectorStore:
    def __init__(self, base_path: str = "app/data/faiss"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.embeddings = get_embeddings_model()

    def _user_dir(self, user_id: str) -> Path:
        user_dir = self.base_path / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _load(self, user_id: str) -> FAISS | None:
        user_dir = self._user_dir(user_id)
        index_file = user_dir / "index.faiss"
        if not index_file.exists():
            return None

        try:
            resolved_user_dir = user_dir.resolve()
            resolved_index_file = index_file.resolve()
            if not str(resolved_index_file).startswith(str(resolved_user_dir)):
                return None
        except Exception:
            return None

        try:
            return FAISS.load_local(
                folder_path=str(user_dir),
                embeddings=self.embeddings,
                allow_dangerous_deserialization=True,
            )
        except Exception:
            return None

    def add_documents(self, user_id: str, docs: list[Document]) -> list[str]:
        if not docs:
            return []

        store = self._load(user_id)
        if store is None:
            store = FAISS.from_documents(docs, self.embeddings)
            ids = list(store.index_to_docstore_id.values())
        else:
            ids = store.add_documents(docs)

        store.save_local(str(self._user_dir(user_id)))
        return ids

    def replace_documents(self, user_id: str, docs: list[Document]) -> list[str]:
        user_dir = self._user_dir(user_id)
        for file in user_dir.glob("*"):
            if file.is_file():
                file.unlink()

        if not docs:
            return []

        store = FAISS.from_documents(docs, self.embeddings)
        ids = list(store.index_to_docstore_id.values())
        store.save_local(str(user_dir))
        return ids

    def similarity_search(self, user_id: str, query: str, top_k: int = 4) -> list[Document]:
        store = self._load(user_id)
        if store is None:
            return []
        return store.similarity_search(query, k=top_k)

    def similarity_search_with_score(self, user_id: str, query: str, top_k: int = 4) -> list[tuple[Document, float]]:
        store = self._load(user_id)
        if store is None:
            return []
        try:
            return store.similarity_search_with_score(query, k=top_k)
        except Exception:
            docs = store.similarity_search(query, k=top_k)
            return [(doc, 1.0) for doc in docs]

    def clear_user_index(self, user_id: str) -> None:
        user_dir = self._user_dir(user_id)
        for file in user_dir.glob("*"):
            if file.is_file():
                file.unlink()


vector_store_manager = UserVectorStore()
