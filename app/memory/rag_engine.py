# app/memory/rag_engine.py

import os
import shutil
from typing import List, Dict, Any
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from app.core.config import settings
from app.core.llm_factory import get_embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


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

        # 加载或初始化三层向量空间
        self.global_store = self._load_store(self.global_dir)
        self.volume_store = self._load_store(self.volume_dir)
        self.phase_store = self._load_store(self.phase_dir)

    # ==========================================
    # 🛠️ 内部存储与加载辅助方法
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

    def _add_documents_to_store(self, store, path, documents):
        """通用向量切片与插入逻辑"""
        split_docs = self.text_splitter.split_documents(documents)
        if store is None:
            store = FAISS.from_documents(split_docs, self.embeddings)
        else:
            store.add_documents(split_docs)
        self._save_store(store, path)
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
        self.global_store = self._add_documents_to_store(self.global_store, self.global_dir, documents)
        print("   [RAG写入] 已将设定法则灌入 🌍 Global 库。")

    def insert_global_events(self, events: List[str], chapter_num: int):
        """【Global 库】供 Memory-Keeper 调用：写入对全书有影响的重大事件、生死大仇、长线伏笔"""
        if not events: return
        documents = [
            Document(page_content=event, metadata={"chapter": chapter_num, "type": "global_event", "level": "global"})
            for event in events
        ]
        self.global_store = self._add_documents_to_store(self.global_store, self.global_dir, documents)

    def insert_chapter_details(self, events: List[str], chapter_num: int):
        """【Volume & Phase 库】供 Memory-Keeper 调用：写入单章的详细动作、对话与微观剧情"""
        if not events: return
        documents = [
            Document(page_content=event, metadata={"chapter": chapter_num, "type": "chapter_detail"})
            for event in events
        ]
        # 单章日常细节同时灌入分卷库和单期库
        self.volume_store = self._add_documents_to_store(self.volume_store, self.volume_dir, documents)
        self.phase_store = self._add_documents_to_store(self.phase_store, self.phase_dir, documents)
        print(f"   [RAG写入] 单章细节已灌入 📜 Volume 库与 🔍 Phase 库 (Chapter {chapter_num})。")

    # ==========================================
    # 🗑️ 遗忘/归档机制 (安全覆盖机制，解决空指针隐患)
    # ==========================================
    def reset_phase_store(self):
            """
            【清理 Phase 库】安全重置机制：不删目录，用占位符覆盖
            """
            dummy_doc = Document(
                page_content="【系统占位】本期剧情刚开始，暂无近期微观细节。",
                metadata={"type": "placeholder", "chapter": 0}
            )
            # 用占位文档直接初始化一个新的 FAISS 库，安全覆盖旧数据
            self.phase_store = FAISS.from_documents([dummy_doc], self.embeddings)
            self._save_store(self.phase_store, self.phase_dir)
            print("🧹 [RAG-Engine] 【单期细节库】已安全清空重建。")

    def reset_volume_store(self):
            """
            【清理 Volume 库】安全重置机制：不删目录，用占位符覆盖
            """
            dummy_doc = Document(
                page_content="【系统占位】本卷剧情刚开始，暂无宏观历史脉络。",
                metadata={"type": "placeholder", "chapter": 0}
            )
            self.volume_store = FAISS.from_documents([dummy_doc], self.embeddings)
            self._save_store(self.volume_store, self.volume_dir)
            print("🧹 [RAG-Engine] 【分卷剧情库】已安全清空重建。")

    # ==========================================
    # 🔭 立体联合检索机制
    # ==========================================
    def retrieve_context(self, query: str, k_global=2, k_volume=2, k_phase=2) -> str:
        """
        供下游 Planner 和 Editor 调用的层级化检索：
        从全局、分卷、单期三个维度分别捞取知识，将返回结果严格分块，防止大模型认知混淆。
        """
        context_str = "【🌟 层级化 RAG 历史与设定参考】\n"

        # 1. 检索全局库 (Global) - 优先级最高，用于校验世界观与大伏笔
        context_str += "--- 🌍 全局法则与大事件 (Global Lore) ---\n"
        if self.global_store:
            global_results = self.global_store.similarity_search(query, k=k_global)
            # 过滤掉可能的占位符
            valid_global = [d for d in global_results if d.metadata.get("type") != "placeholder"]
            if valid_global:
                for i, doc in enumerate(valid_global):
                    context_str += f"{i + 1}. {doc.page_content}\n"
            else:
                context_str += "（暂无全局设定）\n"
        else:
            context_str += "（暂无全局设定）\n"

        # 2. 检索分卷库 (Volume) - 用于串联本卷的起承转合
        context_str += "\n--- 📜 本卷宏观剧情 (Volume Plot) ---\n"
        if self.volume_store:
            volume_results = self.volume_store.similarity_search(query, k=k_volume)
            valid_volume = [d for d in volume_results if d.metadata.get("type") != "placeholder"]
            if valid_volume:
                for i, doc in enumerate(valid_volume):
                    chapter = doc.metadata.get("chapter", "?")
                    context_str += f"{i + 1}. [源自第 {chapter} 章] {doc.page_content}\n"
            else:
                context_str += "（暂无本卷历史）\n"
        else:
            context_str += "（暂无本卷历史）\n"

        # 3. 检索单期库 (Phase) - 用于精准接续上一章的具体场景和对话
        context_str += "\n--- 🔍 本期微观细节 (Phase Detail) ---\n"
        if self.phase_store:
            phase_results = self.phase_store.similarity_search(query, k=k_phase)
            valid_phase = [d for d in phase_results if d.metadata.get("type") != "placeholder"]
            if valid_phase:
                for i, doc in enumerate(valid_phase):
                    chapter = doc.metadata.get("chapter", "?")
                    context_str += f"{i + 1}. [源自第 {chapter} 章] {doc.page_content}\n"
            else:
                context_str += "（暂无本期细节）\n"
        else:
            context_str += "（暂无本期细节）\n"

        return context_str