# app/agents/graph.py
from langgraph.graph import StateGraph, START, END
from typing import Literal

from app.core.state import TomatoNovelState

from app.agents.workers.all_planner import (
    book_planner_node,
    volume_planner_node,
    phase_planner_node,
    chapter_planner_node
)
from app.agents.workers.continuity_editor import continuity_editor_node
from app.agents.workers.chapter_writer import chapter_writer_node
from app.agents.workers.memory_keeper import memory_keeper_node
from app.agents.supervisor import human_review_node


# 注意：删除了 continuity_editor 的引入和 editor_router 函数

def planner_router(state: TomatoNovelState) -> str:
    """🌟 智能前置大纲路由：决定每次发车时的图入口节点"""
    current_chapter_num = state.get("current_chapter_num", 1)
    book_outline = state.get("book_outline_context", "")

    if not book_outline or book_outline.strip() == "":
        print("🔀 [Router] 智能路由分配：新书首发 -> Book_Planner")
        return "Book_Planner"

    # 🌟 修改点：将 30 改为 100，实现 100 章一卷的大地图跨度
    if (current_chapter_num - 1) % 50 == 0:
        print(f"🔀 [Router] 智能路由分配：新卷开启 (第 {current_chapter_num} 章) -> Volume_Planner")
        return "Volume_Planner"

    # 保持 10 章一期不变
    if (current_chapter_num - 1) % 10 == 0:
        print(f"🔀 [Router] 智能路由分配：新期开启 (第 {current_chapter_num} 章) -> Phase_Planner")
        return "Phase_Planner"

    print(f"🔀 [Router] 智能路由分配：常规连载 (第 {current_chapter_num} 章) -> Chapter_Planner")
    return "Chapter_Planner"


def human_review_router(state: TomatoNovelState) -> Literal["Memory_Keeper", "Chapter_Writer"]:
    status = state.get("human_approval_status", "PENDING").upper()
    if status == "APPROVED":
        print("🔀 [Router] 人类总编批准，流转至记忆库进行状态持久化。")
        return "Memory_Keeper"
    else:
        print("🔀 [Router] 人类总编打回，附加强制指令流转至主笔重写。")
        return "Chapter_Writer"

def editor_router(state: TomatoNovelState) -> Literal["Human_Review", "Chapter_Writer"]:
    status = state.get("editor_comments", "PASS")
    if status == "FAIL":
        print("🔀 [Router] 内审未通过，流转回主笔重构细节。")
        return "Chapter_Writer"
    else:
        print("🔀 [Router] 内审通过 (或强行放行)，流转至人类总编审查。")
        return "Human_Review"

def build_workflow() -> StateGraph:
    workflow = StateGraph(TomatoNovelState)

    workflow.add_node("Book_Planner", book_planner_node)
    workflow.add_node("Volume_Planner", volume_planner_node)
    workflow.add_node("Phase_Planner", phase_planner_node)
    workflow.add_node("Chapter_Planner", chapter_planner_node)
    workflow.add_node("Chapter_Writer", chapter_writer_node)
    workflow.add_node("Human_Review", human_review_node)
    workflow.add_node("Memory_Keeper", memory_keeper_node)
    workflow.add_node("Continuity_Editor", continuity_editor_node)

    # 🌟 修改核心：将硬编码的 workflow.add_edge(START, "Book_Planner") 替换为条件路由
    workflow.add_conditional_edges(START, planner_router)

    # 保留内部的顺序级联，如果从高层(如Book_Planner)进入，执行完会自动往下层走
    workflow.add_edge("Book_Planner", "Volume_Planner")
    workflow.add_edge("Volume_Planner", "Phase_Planner")
    workflow.add_edge("Phase_Planner", "Chapter_Planner")
    workflow.add_edge("Chapter_Planner", "Chapter_Writer")
    workflow.add_edge("Chapter_Writer", "Continuity_Editor")
    workflow.add_conditional_edges("Continuity_Editor", editor_router)

    workflow.add_conditional_edges("Human_Review", human_review_router)
    workflow.add_edge("Memory_Keeper", END)

    return workflow