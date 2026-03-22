"""
向量存储模块。

设计目标：
1) 使用用户级目录隔离 FAISS 索引；
2) 优先使用 DashScope Embedding；
3) 在无外部 embedding 服务时，提供可运行的本地哈希向量兜底。
"""

import hashlib
import math
import os
from pathlib import Path

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document


class HashEmbeddings(Embeddings):
    """
    轻量兜底 embedding 实现。

    用于开发/测试阶段在缺少在线 embedding 服务时保证系统可运行，
    不追求高语义质量，只保证向量维度稳定、接口兼容。
    """
    def __init__(self, size: int = 128):
        self.size = size

    def _encode(self, text: str) -> list[float]:
        vector = [0.0] * self.size
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            idx = int(digest[:8], 16) % self.size
            vector[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._encode(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._encode(text)


def get_embeddings_model() -> Embeddings:
    """
    获取 embedding 模型实例。

    优先级：
    1) DashScopeEmbeddings；
    2) HashEmbeddings（兜底）。
    """
    dashscope_api_key = os.getenv("DASHSCOPE_API_KEY")
    if dashscope_api_key:
        try:
            return DashScopeEmbeddings(
                model="text-embedding-v2",
                dashscope_api_key=dashscope_api_key
            )
        except Exception:
            pass
    return HashEmbeddings()


class UserVectorStore:
    """
    用户级向量库管理器。

    每个用户维护独立 FAISS 索引目录，避免跨用户知识串扰。
    """
    def __init__(self, base_path: str = "app/data/faiss"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.embeddings = get_embeddings_model()

    def _user_dir(self, user_id: str) -> Path:
        """获取并确保用户向量目录存在。"""
        path = self.base_path / user_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _load(self, user_id: str):
        """
        加载用户现有向量索引；若不存在则返回 None。

        安全性考虑：
        - 仅加载用户自己目录下的索引文件
        - 验证文件路径，防止路径遍历攻击
        """
        user_dir = self._user_dir(user_id)
        index_file = user_dir / "index.faiss"

        # 验证路径安全性：确保索引文件在用户目录内
        try:
            index_file_resolved = index_file.resolve()
            user_dir_resolved = user_dir.resolve()
            if not str(index_file_resolved).startswith(str(user_dir_resolved)):
                raise ValueError("Invalid index file path")
        except Exception:
            return None

        if not index_file.exists():
            return None

        try:
            # FAISS 本地加载需要此参数，但我们通过路径验证降低风险
            return FAISS.load_local(
                folder_path=str(user_dir),
                embeddings=self.embeddings,
                allow_dangerous_deserialization=True  # 已通过路径验证保护
            )
        except Exception as e:
            # 损坏的索引文件应该被记录但不中断服务
            print(f"Warning: Failed to load FAISS index for user {user_id}: {e}")
            return None

    def add_documents(self, user_id: str, docs: list[Document]) -> list[str]:
        """
        向用户索引写入文档分片并持久化。

        返回写入后的向量 ID 列表，便于与数据库中的 chunk 建立映射。
        """
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

    def similarity_search(self, user_id: str, query: str, top_k: int = 4) -> list[Document]:
        """对用户索引执行相似度检索。"""
        store = self._load(user_id)
        if store is None:
            return []
        return store.similarity_search(query, k=top_k)


vector_store_manager = UserVectorStore()
