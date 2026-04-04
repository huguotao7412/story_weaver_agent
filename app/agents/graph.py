# app/agents/graph.py
from langgraph.graph import StateGraph, START, END
from typing import Literal

from app.core.state import TomatoNovelState

# 🌟 核心修改：导入新的四层规划节点
from app.agents.workers.all_planner import (
    book_planner_node,
    volume_planner_node,
    phase_planner_node,
    chapter_planner_node
)
from app.agents.workers.chapter_writer import chapter_writer_node
from app.agents.workers.continuity_editor import continuity_editor_node
from app.agents.workers.memory_keeper import memory_keeper_node
from app.agents.supervisor import human_review_node


# ==========================================
# 🔀 条件路由判定函数 (保持不变)
# ==========================================
def editor_router(state: TomatoNovelState) -> Literal["Human_Review", "Chapter_Writer"]:
    if state.get("editor_comments") == "PASS":
        print("🔀 [Router] 内部审查通过，流转至人类审核环节。")
        return "Human_Review"
    elif state.get("internal_revision_count", 0) >= 3:
        print("🔀 [Router] ⚠️ 内部审查死循环熔断！重写次数超限，强制流转至总编桌面。")
        return "Human_Review"
    else:
        print(f"🔀 [Router] 内部审查未通过 (第 {state.get('internal_revision_count', 0)} 次)，打回主笔节点返工。")
        return "Chapter_Writer"


def human_review_router(state: TomatoNovelState) -> Literal["Memory_Keeper", "Chapter_Writer"]:
    status = state.get("human_approval_status", "PENDING").upper()
    if status == "APPROVED":
        print("🔀 [Router] 人类总编批准，流转至记忆库进行状态持久化。")
        return "Memory_Keeper"
    else:
        print("🔀 [Router] 人类总编打回，附加强制指令流转至主笔重写。")
        return "Chapter_Writer"


# ==========================================
# 🏗️ 构建 LangGraph 工作流
# ==========================================
def build_workflow() -> StateGraph:
    """构建并编译 StoryWeaver 的核心小说生成流"""

    workflow = StateGraph(TomatoNovelState)

    # 1. 🌟 注册所有核心节点 (替换为四层规划节点)
    workflow.add_node("Book_Planner", book_planner_node)
    workflow.add_node("Volume_Planner", volume_planner_node)
    workflow.add_node("Phase_Planner", phase_planner_node)
    workflow.add_node("Chapter_Planner", chapter_planner_node)

    workflow.add_node("Chapter_Writer", chapter_writer_node)
    workflow.add_node("Editor", continuity_editor_node)
    workflow.add_node("Human_Review", human_review_node)
    workflow.add_node("Memory_Keeper", memory_keeper_node)

    # 2. 🌟 定义常规流转边：从全书到分卷，再到单期，最后到章节
    workflow.add_edge(START, "Book_Planner")
    workflow.add_edge("Book_Planner", "Volume_Planner")
    workflow.add_edge("Volume_Planner", "Phase_Planner")
    workflow.add_edge("Phase_Planner", "Chapter_Planner")
    workflow.add_edge("Chapter_Planner", "Chapter_Writer")
    workflow.add_edge("Chapter_Writer", "Editor")

    # 3. === 第一阶段：内部 AI 互搏循环 ===
    workflow.add_conditional_edges("Editor", editor_router)

    # 4. === 第二阶段：外部人类决断循环 ===
    workflow.add_conditional_edges("Human_Review", human_review_router)

    # 5. 入库完结，准备进入下一章节的循环
    workflow.add_edge("Memory_Keeper", END)

    return workflow