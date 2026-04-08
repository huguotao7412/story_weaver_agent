# app/core/state.py
from typing import Annotated, TypedDict, List, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class TomatoNovelState(TypedDict):
    """引擎级全局事务状态数据结构定义"""

    book_id: str

    chapter_num: int
    is_book_initialized: bool
    is_volume_initialized: bool
    is_phase_initialized: bool


    # 消息总线
    messages: Annotated[List[BaseMessage], add_messages]

    # === 1. 全局配置与静态知识库 (只读区) ===
    target_writing_style: dict
    world_bible_context: str  # 核心世界观

    # 🌟 新增：百万字四层规划状态区
    book_outline_context: str   # 存放第一层：全书10卷总纲
    current_volume_phases: str  # 存放第二层：当前卷的三期拆解
    current_phase_chapters: str # 存放第三层：当前期的10章连贯梗概

    # 检索出的历史剧情/伏笔
    recent_chapters_summary: str  # 存放前情提要摘要
    rag_history_context: str
    previous_chapter_ending: str

    # === 2. 当前章节工作区 (事务隔离的草稿区) ===
    current_chapter_num: int
    current_beat_sheet: str     # 存放第四层：单章节拍器
    draft_path: str

    # === 3. 内部 AI 互搏区 ===
    editor_comments: str
    internal_revision_count: int

    # === 4. 人类最高权限干涉区 (HITL) ===
    human_approval_status: str
    human_feedback: str
    direct_edits: str