# app/memory/rag_engine.py
import os
import math
from typing import List, Dict, Any
from collections import OrderedDict, Counter
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
import threading

from app.core.config import settings
from app.core.llm_factory import get_embeddings, rerank_documents


class IncrementalBM25:
    """🌟 工业级轻量优化：增量 BM25 检索引擎，插入时 O(1)，杜绝全量重算的 CPU 阻塞"""

    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.N = 0
        self.doc_freqs = Counter()
        self.doc_lengths = []
        self.total_length = 0
        self.corpus_term_freqs = []
        self.docs = []

    def add_documents(self, docs):
        """增量写入，只累加词频，不做全量矩阵重构"""
        for doc in docs:
            tokens = list(doc.page_content)  # 按照字符级切分
            length = len(tokens)
            self.docs.append(doc)
            self.doc_lengths.append(length)
            self.total_length += length
            self.N += 1

            term_freq = Counter(tokens)
            self.corpus_term_freqs.append(term_freq)
            for term in term_freq.keys():
                self.doc_freqs[term] += 1

    def get_top_n(self, query_tokens, n=5):
        """即时计算 IDF 与 TF，返回高分文档"""
        if self.N == 0: return []
        avgdl = self.total_length / self.N
        scores = []
        for i in range(self.N):
            score = 0
            doc_len = self.doc_lengths[i]
            term_freqs = self.corpus_term_freqs[i]
            for q in query_tokens:
                if q not in term_freqs: continue
                # 动态计算 IDF
                nq = self.doc_freqs.get(q, 0)
                idf = math.log((self.N - nq + 0.5) / (nq + 0.5) + 1)
                # 动态计算 TF
                tf = term_freqs[q]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * (doc_len / avgdl))
                score += idf * (numerator / denominator)
            if score > 0:
                scores.append((score, self.docs[i]))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [doc for score, doc in scores[:n]]


class ThreadSafeLRUCache:
    def __init__(self, capacity: int):
        self.cache = OrderedDict()
        self.capacity = capacity
        self.lock = threading.Lock()

    def get(self, key: str):
        with self.lock:
           if key not in self.cache: return None
           self.cache.move_to_end(key)
           return self.cache[key]

    def put(self, key: str, value):
        with self.lock:
           self.cache[key] = value
           self.cache.move_to_end(key)
           if len(self.cache) > self.capacity:
              self.cache.popitem(last=False)


# 全局共享实例 (跨请求存活)
GLOBAL_BM25_CACHE = ThreadSafeLRUCache(capacity=50)


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

        self.book_id = book_id
        # 加载或初始化三层向量空间
        self.global_store = self._load_store(self.global_dir)
        self.volume_store = self._load_store(self.volume_dir)
        self.phase_store = self._load_store(self.phase_dir)

        # 🌟 初始化时预热构建一次缓存
        GLOBAL_BM25_CACHE.put(f"{self.book_id}_global", self._build_bm25_cache(self.global_store))
        GLOBAL_BM25_CACHE.put(f"{self.book_id}_volume", self._build_bm25_cache(self.volume_store))
        GLOBAL_BM25_CACHE.put(f"{self.book_id}_phase", self._build_bm25_cache(self.phase_store))

    # ==========================================
    # 🛠️ 内部存储与缓存构建辅助方法
    # ==========================================
    def _load_store(self, path):
        """尝试加载本地 FAISS 索引"""
        index_path = os.path.join(path, "index.faiss")
        if os.path.exists(index_path):
            try:
                # 尝试加载，如果文件损坏会抛出异常
                return FAISS.load_local(path, self.embeddings, allow_dangerous_deserialization=True)
            except Exception as e:
                print(f"⚠️ [RAG-Engine] 检测到索引文件损坏，正在抛弃损坏档 ({e})")
                # 发生损坏直接当作没有库，返回 None，让系统自动从零重新构建
                return None
        return None

    def _save_store(self, store, path):
        """持久化保存 FAISS 索引到硬盘"""
        if store:
            os.makedirs(path, exist_ok=True)
            store.save_local(path)

    def _build_bm25_cache(self, store):
        """初始化全量构建 BM25 (仅在系统刚启动，读取历史数据时执行一次)"""
        if store is None:
            return None
        valid_docs = [d for d in store.docstore._dict.values() if d.metadata.get("type") != "placeholder"]
        if not valid_docs:
            return None

        bm25 = IncrementalBM25()
        bm25.add_documents(valid_docs)
        return bm25

    def _add_documents_to_store(self, store, path, documents, cache_key: str):
        """🌟 核心优化：向量走 FAISS，BM25 走内存增量更新（毫无阻塞）"""
        split_docs = self.text_splitter.split_documents(documents)

        # 1. 持久化更新 FAISS
        if store is None:
            store = FAISS.from_documents(split_docs, self.embeddings)
        else:
            store.add_documents(split_docs)
        self._save_store(store, path)

        # 2. 内存级别极速增量更新 BM25
        bm25_obj = GLOBAL_BM25_CACHE.get(f"{self.book_id}_{cache_key}")
        if bm25_obj is None:
            bm25_obj = IncrementalBM25()
            GLOBAL_BM25_CACHE.put(f"{self.book_id}_{cache_key}", bm25_obj)

        bm25_obj.add_documents(split_docs)
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
        # 🌟 同步刷新全局缓存，修复原版 self.bm25_caches 不存在的报错
        GLOBAL_BM25_CACHE.put(f"{self.book_id}_phase", self._build_bm25_cache(self.phase_store))
        print("🧹 [RAG-Engine] 【单期细节库】已安全清空重建。")

    def reset_volume_store(self):
        """【清理 Volume 库】安全重置机制：不删目录，用占位符覆盖"""
        dummy_doc = Document(
            page_content="【系统占位】本卷剧情刚开始，暂无宏观历史脉络。",
            metadata={"type": "placeholder", "chapter": 0}
        )
        self.volume_store = FAISS.from_documents([dummy_doc], self.embeddings)
        self._save_store(self.volume_store, self.volume_dir)
        # 🌟 同步刷新全局缓存
        GLOBAL_BM25_CACHE.put(f"{self.book_id}_volume", self._build_bm25_cache(self.volume_store))
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
            faiss_docs = store.similarity_search(
                query,
                k=recall_k,
                filter=lambda metadata: metadata.get("type") != "placeholder"
            )

            # == 通道二：BM25 缓存召回 (🚀 极大降低 CPU 开销) ==
            bm25 = GLOBAL_BM25_CACHE.get(f"{self.book_id}_{cache_key}")
            if bm25 and bm25.N > 0:
                tokenized_query = list(query)
                bm25_docs = bm25.get_top_n(tokenized_query, n=recall_k)
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
            if 'candidate_docs' in locals() and candidate_docs:
                return candidate_docs[:k]
            return store.similarity_search(
                query,
                k=k,
                filter=lambda metadata: metadata.get("type") != "placeholder"
            )

    def retrieve_context(self, query: str, k_global=2, k_volume=2, k_phase=2) -> str:
        """
        供下游 Planner 和 Editor 调用的层级化检索
        """
        if not query or not query.strip():
            return "（未提供有效的检索关键词，暂无关联历史）"
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