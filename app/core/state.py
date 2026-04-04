# app/core/state.py
from typing import Annotated, TypedDict, List, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class TomatoNovelState(TypedDict):
    """引擎级全局事务状态数据结构定义"""

    # 消息总线，记录多轮对话轨迹
    messages: Annotated[List[BaseMessage], add_messages]

    # === 1. 全局配置与静态知识库 (只读区) ===
    # 🌟 修复：移除导致报错的 SharedValue，直接使用 dict，LangGraph 默认会覆盖更新
    target_writing_style: dict
    world_bible_context: str  # FAISS 检索出的世界观与历史剧情快照

    # 🌟 新增字段：基于大纲反向检索出的历史剧情/伏笔
    rag_history_context: str

    # === 2. 当前章节工作区 (事务隔离的草稿区) ===
    current_chapter_num: int  # 当前正在生成的章节号
    current_beat_sheet: str  # 层次化生成的本章大纲树节点（JSON 字符串）
    draft_content: str  # 正在持续迭代的草稿文本（批准前绝不入库）

    # === 3. 内部 AI 互搏区 ===
    editor_comments: str  # 内部逻辑审查结果 ("PASS" 或具体的 bug 提示)

    # === 4. 🌟 人类最高权限干涉区 (HITL) ===
    human_approval_status: str  # 事务控制: "PENDING", "REJECTED", "APPROVED"
    human_feedback: str  # 递归规划注入的人类批注指令