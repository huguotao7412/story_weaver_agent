# app/agents/routers.py
"""Routing functions for workflow conditional edges. These serve as the Python fallback
for complex conditions that cannot be expressed in workflow.yaml expressions."""

from typing import Literal


def planner_router(state: dict) -> str:
    """智能前置大纲路由：决定每次发车时的图入口节点"""
    current_chapter_num = state.get("current_chapter_num", 1)
    is_initialized = state.get("is_book_initialized", False)

    if not is_initialized:
        print("🔀 [Router] 智能路由分配：新书首发 -> Book_Planner")
        return "Book_Planner"

    # 实现 50 章一卷的大地图跨度
    if (current_chapter_num - 1) % 50 == 0:
        print(f"🔀 [Router] 智能路由分配：新卷开启 (第 {current_chapter_num} 章) -> Volume_Planner")
        return "Volume_Planner"

    # 保持 10 章一期不变
    if (current_chapter_num - 1) % 10 == 0:
        print(f"🔀 [Router] 智能路由分配：新期开启 (第 {current_chapter_num} 章) -> Phase_Planner")
        return "Phase_Planner"

    print(f"🔀 [Router] 智能路由分配：常规连载 (第 {current_chapter_num} 章) -> Chapter_Planner")
    return "Chapter_Planner"


def human_review_router(state: dict) -> Literal["Memory_Keeper", "Chapter_Writer"]:
    """人类总编审批后的路由"""
    status = state.get("human_approval_status", "PENDING").upper()
    if status == "APPROVED":
        print("🔀 [Router] 人类总编批准，流转至记忆库进行状态持久化。")
        return "Memory_Keeper"
    else:
        print("🔀 [Router] 人类总编打回，附加强制指令流转至主笔重写。")
        return "Chapter_Writer"


def editor_router(state: dict) -> Literal["Human_Review", "Chapter_Writer"]:
    """内部质检后的路由"""
    status = state.get("editor_comments", "PASS")
    if status == "FAIL":
        print("🔀 [Router] 内审未通过，流转回主笔重构细节。")
        return "Chapter_Writer"
    else:
        print("🔀 [Router] 内审通过 (或强行放行)，流转至人类总编审查。")
        return "Human_Review"
