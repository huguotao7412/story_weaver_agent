# app/core/state.py
from typing import TypedDict, List


class GlobalConfig(TypedDict, total=False):
    """全局只读配置（重文本已迁至 AsyncKVTracker.temp_ctx_*）"""
    book_id: str
    target_writing_style: dict


class PlanningContext(TypedDict, total=False):
    """四层大纲规划标记位（大纲正文在 KV tracker 中）"""
    is_book_initialized: bool
    is_volume_initialized: bool
    is_phase_initialized: bool


class ChapterWorkspace(TypedDict, total=False):
    """当前章节工作区"""
    current_chapter_num: int
    draft_path: str
    recent_chapters_summary: List[str]
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
    """引擎级全局事务状态数据结构。重文本迁移至 AsyncKVTracker，LangGraph 只存标记与计数器。"""
    pass
