# app/memory/rag_engine.py

import os
import shutil
from typing import List, Dict, Any
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from app.core.config import settings
from app.core.llm_factory import get_embeddings, rerank_documents
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi


class RAGEngine:
    """
    🧠 百万字长篇专用：三层层级化向量检索引擎 (Hierarchical RAG)
    Global(全局) -> Volume(分卷) -> Phase(单期)
    """

    def __init__(self, book_id: str = "default_book"):
        self.base_dir = os.path.join(settings.DATA_DIR, book_id, "faiss_index")

        # 🌟 为三层库分别建立独立的物理存储路径
        self.global_dir = os.path.join(self.base_dir, "global_lore")
        self.volume_dir = os.path.join(self.base_dir, "current_volume")
        self.phase_dir = os.path.join(self.base_dir, "current_phase")

        # 确保基础目录存在
        os.makedirs(self.base_dir, exist_ok=True)

        self.embeddings = get_embeddings()
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100,
            separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""]
        )

        # 🌟 初始化 BM25 内存缓存字典
        self.bm25_caches = {
            "global": None,
            "volume": None,
            "phase": None
        }

        # 加载或初始化三层向量空间
        self.global_store = self._load_store(self.global_dir)
        self.volume_store = self._load_store(self.volume_dir)
        self.phase_store = self._load_store(self.phase_dir)

        # 🌟 初始化时预热构建一次缓存
        self.bm25_caches["global"] = self._build_bm25_cache(self.global_store)
        self.bm25_caches["volume"] = self._build_bm25_cache(self.volume_store)
        self.bm25_caches["phase"] = self._build_bm25_cache(self.phase_store)

    # ==========================================
    # 🛠️ 内部存储与缓存构建辅助方法
    # ==========================================
    def _load_store(self, path):
        """尝试加载本地 FAISS 索引"""
        if os.path.exists(os.path.join(path, "index.faiss")):
            return FAISS.load_local(path, self.embeddings, allow_dangerous_deserialization=True)
        return None

    def _save_store(self, store, path):
        """持久化保存 FAISS 索引到硬盘"""
        if store:
            os.makedirs(path, exist_ok=True)
            store.save_local(path)

    def _build_bm25_cache(self, store):
        """🌟 核心优化：基于当前的 FAISS Store 在内存中静态构建 BM25 索引"""
        if store is None:
            return None
        valid_docs = [d for d in store.docstore._dict.values() if d.metadata.get("type") != "placeholder"]
        if not valid_docs:
            return None
        tokenized_corpus = [list(doc.page_content) for doc in valid_docs]
        return {"bm25": BM25Okapi(tokenized_corpus), "docs": valid_docs}

    def _add_documents_to_store(self, store, path, documents, cache_key: str):
        """🌟 核心优化：通用向量切片与插入逻辑（同步更新 BM25 缓存）"""
        split_docs = self.text_splitter.split_documents(documents)
        if store is None:
            store = FAISS.from_documents(split_docs, self.embeddings)
        else:
            store.add_documents(split_docs)
        self._save_store(store, path)

        # 写入后立即刷新当前库的 BM25 缓存。检索时直接调缓存，实现 O(1) 检索
        self.bm25_caches[cache_key] = self._build_bm25_cache(store)
        return store

    # ==========================================
    # ✍️ 写入方法：分类灌入三层库
    # ==========================================
    def insert_world_bible(self, lore_entries: List[Dict[str, str]]):
        """【Global 库】仅供 Book-Planner 调用：写入世界观、核心设定、十卷总纲"""
        documents = [
            Document(page_content=f"【{lore['title']}】: {lore['content']}",
                     metadata={"type": "world_lore", "level": "global"})
            for lore in lore_entries
        ]
        self.global_store = self._add_documents_to_store(self.global_store, self.global_dir, documents, "global")
        print("   [RAG写入] 已将设定法则灌入 🌍 Global 库。")

    def insert_global_events(self, events: List[str], chapter_num: int):
        """【Global 库】供 Memory-Keeper 调用：写入对全书有影响的重大事件、生死大仇、长线伏笔"""
        if not events: return
        documents = [
            Document(page_content=event, metadata={"chapter": chapter_num, "type": "global_event", "level": "global"})
            for event in events
        ]
        self.global_store = self._add_documents_to_store(self.global_store, self.global_dir, documents, "global")

    def insert_chapter_details(self, events: List[str], chapter_num: int):
        """【Volume & Phase 库】供 Memory-Keeper 调用：写入单章的详细动作、对话与微观剧情"""
        if not events: return
        documents = [
            Document(page_content=event, metadata={"chapter": chapter_num, "type": "chapter_detail"})
            for event in events
        ]
        # 单章日常细节同时灌入分卷库和单期库
        self.volume_store = self._add_documents_to_store(self.volume_store, self.volume_dir, documents, "volume")
        self.phase_store = self._add_documents_to_store(self.phase_store, self.phase_dir, documents, "phase")
        print(f"   [RAG写入] 单章细节已灌入 📜 Volume 库与 🔍 Phase 库 (Chapter {chapter_num})。")

    # ==========================================
    # 🗑️ 遗忘/归档机制 (安全覆盖机制，解决空指针隐患)
    # ==========================================
    def reset_phase_store(self):
        """【清理 Phase 库】安全重置机制：不删目录，用占位符覆盖"""
        dummy_doc = Document(
            page_content="【系统占位】本期剧情刚开始，暂无近期微观细节。",
            metadata={"type": "placeholder", "chapter": 0}
        )
        self.phase_store = FAISS.from_documents([dummy_doc], self.embeddings)
        self._save_store(self.phase_store, self.phase_dir)
        # 🌟 重置时务必同步刷新缓存！
        self.bm25_caches["phase"] = self._build_bm25_cache(self.phase_store)
        print("🧹 [RAG-Engine] 【单期细节库】已安全清空重建。")

    def reset_volume_store(self):
        """【清理 Volume 库】安全重置机制：不删目录，用占位符覆盖"""
        dummy_doc = Document(
            page_content="【系统占位】本卷剧情刚开始，暂无宏观历史脉络。",
            metadata={"type": "placeholder", "chapter": 0}
        )
        self.volume_store = FAISS.from_documents([dummy_doc], self.embeddings)
        self._save_store(self.volume_store, self.volume_dir)
        # 🌟 重置时务必同步刷新缓存！
        self.bm25_caches["volume"] = self._build_bm25_cache(self.volume_store)
        print("🧹 [RAG-Engine] 【分卷剧情库】已安全清空重建。")

    # ==========================================
    # 🔭 立体联合检索机制
    # ==========================================
    def _hybrid_search(self, store, cache_key: str, query: str, k: int) -> list[Document]:
        """
        🔍 终极版混合检索：FAISS + BM25 (直接调取内存缓存) -> Rerank (交叉编码器精排)
        """
        if store is None or k <= 0:
            return []

        try:
            all_docs = list(store.docstore._dict.values())
            valid_docs = [d for d in all_docs if d.metadata.get("type") != "placeholder"]
            if not valid_docs:
                return []

            # 🌟 1. 扩大召回基数 (Recall)
            recall_k = max(k * 3, 10)
            recall_k = min(recall_k, len(valid_docs))  # 不能超过总文档数

            # == 通道一：FAISS 向量召回 ==
            faiss_docs = store.similarity_search(query, k=recall_k)
            faiss_docs = [d for d in faiss_docs if d.metadata.get("type") != "placeholder"]

            # == 通道二：BM25 缓存召回 (🚀 极大降低 CPU 开销) ==
            bm25_data = self.bm25_caches.get(cache_key)
            if bm25_data and bm25_data['docs']:
                bm25 = bm25_data['bm25']
                bm25_valid_docs = bm25_data['docs']
                tokenized_query = list(query)
                bm25_docs = bm25.get_top_n(tokenized_query, bm25_valid_docs, n=recall_k)
            else:
                bm25_docs = []

            # 🌟 2. 候选池去重合并 (Union)
            unique_candidate_docs = {}
            for d in faiss_docs + bm25_docs:
                unique_candidate_docs[d.page_content] = d

            candidate_docs = list(unique_candidate_docs.values())

            # 如果去重后不够目标数量，直接返回
            if len(candidate_docs) <= k:
                return candidate_docs[:k]

            # 🌟 3. Rerank 终极精排 (Precision)
            doc_texts = [d.page_content for d in candidate_docs]
            sorted_indices = rerank_documents(query, doc_texts, top_n=k)
            final_docs = [candidate_docs[i] for i in sorted_indices]

            return final_docs

        except Exception as e:
            print(f"⚠️ [RAG-Engine] 检索/重排构建失败，平滑降级: {e}")
            raw_results = store.similarity_search(query, k=k)
            return [d for d in raw_results if d.metadata.get("type") != "placeholder"]

    def retrieve_context(self, query: str, k_global=2, k_volume=2, k_phase=2) -> str:
        """
        供下游 Planner 和 Editor 调用的层级化检索
        """
        context_str = "【🌟 层级化 RAG 历史与设定参考】\n"

        # 1. 混合检索全局库 (Global)
        context_str += "--- 🌍 全局法则与大事件 (Global Lore) ---\n"
        global_results = self._hybrid_search(self.global_store, "global", query, k_global)
        if global_results:
            for i, doc in enumerate(global_results):
                context_str += f"{i + 1}. {doc.page_content}\n"
        else:
            context_str += "（暂无全局设定）\n"

        # 2. 混合检索分卷库 (Volume)
        context_str += "\n--- 📜 本卷宏观剧情 (Volume Plot) ---\n"
        volume_results = self._hybrid_search(self.volume_store, "volume", query, k_volume)
        if volume_results:
            for i, doc in enumerate(volume_results):
                chapter = doc.metadata.get("chapter", "?")
                context_str += f"{i + 1}. [源自第 {chapter} 章] {doc.page_content}\n"
        else:
            context_str += "（暂无本卷历史）\n"

        # 3. 混合检索单期库 (Phase)
        context_str += "\n--- 🔍 本期微观细节 (Phase Detail) ---\n"
        phase_results = self._hybrid_search(self.phase_store, "phase", query, k_phase)
        if phase_results:
            for i, doc in enumerate(phase_results):
                chapter = doc.metadata.get("chapter", "?")
                context_str += f"{i + 1}. [源自第 {chapter} 章] {doc.page_content}\n"
        else:
            context_str += "（暂无本期细节）\n"

        return context_str