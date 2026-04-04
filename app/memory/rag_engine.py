# 世界观检索：基于 FAISS 提供设定查询
# 🧠 RAG 检索引擎：基于 FAISS 管理长线历史剧情与世界观设定
# app/memory/rag_engine.py

import os
from typing import List, Dict, Any
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from app.core.config import settings
from app.core.llm_factory import get_llm, get_embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


class RAGEngine:
    """
    小说全局事件与设定向量检索引擎。
    负责将非结构化的历史剧情、长线伏笔持久化为向量，并在后续生成中提供检索。
    """

    def __init__(self, persist_dir: str = None):
        if persist_dir is None:
            persist_dir = settings.FAISS_DB_PATH

        self.persist_dir = persist_dir
        # 确保 data 目录存在
        os.makedirs(os.path.dirname(self.persist_dir), exist_ok=True)

        # 初始化 Embedding 模型
        # 这里默认使用 OpenAI 的 text-embedding-3-small。如果您是纯本地环境，可换成 BAAI/bge-large-zh-v1.5
        self.embeddings = get_embeddings()

        # 尝试加载已有的本地向量库，如果不存在则初始化为空
        if os.path.exists(os.path.join(persist_dir, "index.faiss")):
            print(f"📖 [RAG-Engine] 检测到本地历史剧情库，正在加载: {persist_dir}")
            self.vector_store = FAISS.load_local(
                persist_dir,
                self.embeddings,
                allow_dangerous_deserialization=True  # 信任本地文件时开启
            )
        else:
            print("📖 [RAG-Engine] 未检测到历史库，初始化全新向量空间。")
            self.vector_store = None

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100,
            # 优先按照段落和句子来切分，最大限度保留网文的语义连贯性
            separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""]
        )

    def insert_events(self, events: List[str], chapter_num: int):
        """
        供 Memory_Keeper 调用：将定稿章节的全局事件(Global Events)写入向量库
        """
        if not events:
            return

        # 将纯文本事件封装为带 Metadata 的 Document 对象
        documents = [
            Document(
                page_content=event,
                metadata={"chapter": chapter_num, "type": "plot_event"}
            ) for event in events
        ]

        split_docs = self.text_splitter.split_documents(documents)

        if self.vector_store is None:
            # 首次插入，创建新的库
            self.vector_store = FAISS.from_documents(documents, self.embeddings)
        else:
            # 追加到现有库
            self.vector_store.add_documents(documents)

        # 立即持久化到本地 data 目录
        self.vector_store.save_local(self.persist_dir)
        print(f"   [RAG写入] 成功将 {len(events)} 条事件写入向量空间 (Chapter {chapter_num})")

    def insert_world_bible(self, lore_entries: List[Dict[str, str]]):
        """
        【初始化阶段调用】：将世界观设定（如派系、地理、力量体系）灌入 RAG
        格式示例：[{"title": "修仙境界", "content": "分为炼气、筑基、金丹..."}]
        """
        documents = [
            Document(
                page_content=f"【{lore['title']}】: {lore['content']}",
                metadata={"type": "world_lore", "title": lore["title"]}
            ) for lore in lore_entries
        ]

        if self.vector_store is None:
            self.vector_store = FAISS.from_documents(documents, self.embeddings)
        else:
            self.vector_store.add_documents(documents)

        self.vector_store.save_local(self.persist_dir)

    def retrieve_context(self, query: str, k: int = 3) -> str:
        """
        供 Plot_Planner 或 Chapter_Writer 调用：根据当前大纲的关键字，捞取历史伏笔
        """
        if self.vector_store is None:
            return "（当前暂无长线历史剧情可供参考）"

        # 执行相似度检索
        results = self.vector_store.similarity_search(query, k=k)

        if not results:
            return "（检索未命中相关历史剧情）"

        context_str = "【历史剧情/伏笔参考】：\n"
        for i, doc in enumerate(results):
            chapter = doc.metadata.get("chapter", "设定")
            context_str += f"{i + 1}. [源自第 {chapter} 章] {doc.page_content}\n"

        return context_str