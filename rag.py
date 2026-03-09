"""
RAG（检索增强生成）— 向量化知识库，每次只检索最相关的片段

启动时：将知识库切片并向量化，存入内存
每次问答：只把与问题最相关的 top-K 片段放进 prompt
好处：节省 token、降低 API 费用、提升回答准确率
"""

import logging
import math
import time
import requests
import numpy as np
from typing import Optional

logger = logging.getLogger(__name__)


class RAGIndex:
    """
    向量化知识库索引。

    用法：
        index = RAGIndex(api_key=..., embed_url=..., model=..., top_k=5)
        index.build(knowledge_text)      # 启动时调用一次
        context = index.retrieve(query)  # 每次问答时调用
    """

    def __init__(
        self,
        api_key: str,
        embed_url: str,
        model: str,
        top_k: int = 5,
        chunk_size: int = 800,
        batch_size: int = 10,  # Dashscope text-embedding-v3 单批最多 10 条
    ):
        self.api_key = api_key
        self.embed_url = embed_url
        self.model = model
        self.top_k = top_k
        self.chunk_size = chunk_size
        self.batch_size = batch_size  # 每批最多向量化多少个 chunk

        self._chunks: list[str] = []
        self._embeddings: Optional[np.ndarray] = None  # shape: (n_chunks, dim)
        self._ready = False

    @property
    def is_ready(self) -> bool:
        return self._ready

    # ── 构建索引 ───────────────────────────────────────────────────────────────

    def build(self, knowledge_text: str) -> bool:
        """
        切片 + 向量化整个知识库，构建内存索引。
        成功返回 True，失败返回 False（调用方应降级为全量模式）。
        """
        if not knowledge_text.strip():
            logger.info("知识库为空，跳过 RAG 索引构建")
            return False

        chunks = self._split(knowledge_text)
        if not chunks:
            return False

        logger.info(f"知识库已切分为 {len(chunks)} 个片段，开始向量化...")
        t0 = time.time()

        embeddings = self._embed_batch(chunks)
        if embeddings is None:
            logger.warning("向量化失败，将回退到全量知识库模式")
            return False

        self._chunks = chunks
        self._embeddings = embeddings
        self._ready = True
        logger.info(f"RAG 索引构建完成：{len(chunks)} 个片段，耗时 {time.time() - t0:.1f}s")
        return True

    def rebuild(self, knowledge_text: str) -> bool:
        """热更新：/reload 指令触发时重建索引"""
        self._ready = False
        self._chunks = []
        self._embeddings = None
        return self.build(knowledge_text)

    # ── 检索 ──────────────────────────────────────────────────────────────────

    def retrieve(self, query: str) -> str:
        """
        检索与 query 最相关的 top_k 个片段，返回合并后的文本。
        索引未就绪时返回空字符串（由调用方决定是否 fallback 到全量）。
        """
        if not self._ready or self._embeddings is None:
            return ""

        query_emb = self._embed_one(query)
        if query_emb is None:
            return ""

        # 余弦相似度：embeddings 已 L2 归一化，直接点积即可
        scores = self._embeddings @ query_emb
        top_k = min(self.top_k, len(self._chunks))
        top_indices = np.argsort(scores)[::-1][:top_k]

        # 按原始顺序排列，保持文档连贯性
        top_indices = sorted(top_indices.tolist())
        retrieved = [self._chunks[i] for i in top_indices]

        logger.info(
            f"RAG 检索完成：返回 {len(retrieved)} 片段，"
            f"最高相似度 {float(scores[top_indices[0]]):.3f}"
            if top_indices else "RAG 检索无结果"
        )
        return "\n\n".join(retrieved)

    # ── 内部：切片 ────────────────────────────────────────────────────────────

    def _split(self, text: str) -> list[str]:
        """
        按知识库格式（=== 文件名 ===）分文件，大文件按段落进一步切分。
        保证每个 chunk 不超过 chunk_size 字符。
        """
        # 按 === xxx === 分隔符拆成若干 section
        sections: list[tuple[str, str]] = []
        current_header = ""
        current_lines: list[str] = []

        for line in text.splitlines():
            if line.startswith("=== ") and line.endswith(" ==="):
                if current_lines:
                    sections.append((current_header, "\n".join(current_lines).strip()))
                current_header = line
                current_lines = []
            else:
                current_lines.append(line)

        if current_lines:
            sections.append((current_header, "\n".join(current_lines).strip()))

        # 每个 section 切成若干 chunk
        chunks: list[str] = []
        for header, body in sections:
            prefix = f"{header}\n" if header else ""
            full = prefix + body
            if len(full) <= self.chunk_size:
                if full.strip():
                    chunks.append(full)
            else:
                chunks.extend(self._split_section(prefix, body))

        return [c for c in chunks if c.strip()]

    def _split_section(self, prefix: str, body: str) -> list[str]:
        """将单个大 section 按段落切分，带 200 字符的滑动重叠"""
        OVERLAP = 200
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        chunks: list[str] = []
        current = prefix

        for para in paragraphs:
            candidate = current + ("\n\n" if current != prefix else "") + para
            if len(candidate) > self.chunk_size and len(current) > len(prefix):
                chunks.append(current.strip())
                # 重叠：保留上一段的后 OVERLAP 字符作为下一 chunk 的开头
                overlap_text = current[-OVERLAP:] if len(current) > OVERLAP else current
                current = prefix + overlap_text + "\n\n" + para
            else:
                current = candidate

        if current.strip() and current.strip() != prefix.strip():
            chunks.append(current.strip())

        return chunks

    # ── 内部：Embedding API 调用 ──────────────────────────────────────────────

    def _embed_batch(self, texts: list[str]) -> Optional[np.ndarray]:
        """批量获取 embeddings，分批请求避免超时，返回 L2 归一化后的 numpy 数组"""
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i: i + self.batch_size]
            result = self._call_embed_api(batch)
            if result is None:
                return None
            all_embeddings.extend(result)
            logger.info(f"向量化进度：{min(i + self.batch_size, len(texts))}/{len(texts)}")

        arr = np.array(all_embeddings, dtype=np.float32)
        # L2 归一化，使后续点积等于余弦相似度
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        return arr / norms

    def _embed_one(self, text: str) -> Optional[np.ndarray]:
        """获取单个 query 的 embedding，返回归一化向量"""
        result = self._call_embed_api([text])
        if result is None:
            return None
        vec = np.array(result[0], dtype=np.float32)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def _call_embed_api(self, texts: list[str]) -> Optional[list[list[float]]]:
        """调用 embedding API，返回原始 embedding 列表"""
        try:
            resp = requests.post(
                self.embed_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "input": texts},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            data.sort(key=lambda x: x["index"])
            return [item["embedding"] for item in data]
        except Exception as e:
            logger.error(f"Embedding API 调用失败: {e}")
            return None
