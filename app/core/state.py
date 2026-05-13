# app/core/state.py
from typing import Annotated, TypedDict, List, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class GlobalConfig(TypedDict, total=False):
    """全局只读配置"""
    book_id: str
    world_bible_context: str
    target_writing_style: dict


class PlanningContext(TypedDict, total=False):
    """四层大纲规划"""
    book_outline_context: str
    current_volume_phases: str
    current_phase_chapters: str
    current_beat_sheet: str
    is_book_initialized: bool
    is_volume_initialized: bool
    is_phase_initialized: bool


class ChapterWorkspace(TypedDict, total=False):
    """当前章节工作区"""
    current_chapter_num: int
    draft_path: str
    recent_chapters_summary: List[str]
    rag_history_context: str
    previous_chapter_ending: str
    editor_comments: str
    internal_revision_count: int
    revision_history: List[str]


class HITLContext(TypedDict, total=False):
    """人类干预区"""
    human_approval_status: str
    human_feedback: str
    direct_edits: str
    user_input: str


class TomatoNovelState(GlobalConfig, PlanningContext, ChapterWorkspace, HITLContext, total=False):
    """引擎级全局事务状态数据结构。通过多继承合并四个语义分组。"""
    pass
