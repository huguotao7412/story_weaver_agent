# 核心图编排：定义节点流转、双向循环与中断断点
# 🕸️ 核心工作流图编排：LangGraph 两段式路由与人类在环
# app/agents/graph.py
from langgraph.graph import StateGraph, START, END
from typing import Literal

# 导入核心状态结构
from app.core.state import TomatoNovelState

# 导入所有 Worker Nodes
# 🌟 核心修改：导入新增的宏观规划节点
from app.agents.workers.all_planner import plot_planner_node, macro_planner_node
from app.agents.workers.chapter_writer import chapter_writer_node
from app.agents.workers.continuity_editor import continuity_editor_node
from app.agents.workers.memory_keeper import memory_keeper_node

# 导入 Supervisor / HITL Node
from app.agents.supervisor import human_review_node


# ==========================================
# 🔀 条件路由判定函数
# ==========================================
def editor_router(state: TomatoNovelState) -> Literal["Human_Review", "Chapter_Writer"]:
    """
    第一阶段条件路由：逻辑审查员的决断
    如果 Editor 返回 PASS，则提交给人类总编审核；否则打回给主笔重写。
    """
    if state.get("editor_comments") == "PASS":
        print("🔀 [Router] 内部审查通过，流转至人类审核环节。")
        return "Human_Review"
    elif state.get("internal_revision_count", 0) >= 3:
        print("🔀 [Router] ⚠️ 内部审查死循环熔断！重写次数超限，强制流转至总编桌面。")
        # 直接让流程挂起，把带有 Bug 的草稿和 Editor 的抱怨一起展示给人类，让人类定夺
        return "Human_Review"
    else:
        print(f"🔀 [Router] 内部审查未通过 (第 {state.get('internal_revision_count', 0)} 次)，打回主笔节点返工。")
        return "Chapter_Writer"


def human_review_router(state: TomatoNovelState) -> Literal["Memory_Keeper", "Chapter_Writer"]:
    """
    第二阶段条件路由：人类总编的最高决断
    如果人类点击 APPROVED，则进入定稿记忆入库阶段；如果 REJECTED，则带着人类指令打回重写。
    """
    status = state.get("human_approval_status", "PENDING").upper()
    if status == "APPROVED":
        print("🔀 [Router] 人类总编批准，流转至记忆库进行状态持久化。")
        return "Memory_Keeper"
    else:
        # 只要不是明确的 APPROVED（比如 REJECTED），都打回给主笔重写
        print("🔀 [Router] 人类总编打回，附加强制指令流转至主笔重写。")
        return "Chapter_Writer"


# ==========================================
# 🏗️ 构建 LangGraph 工作流
# ==========================================
def build_workflow() -> StateGraph:
    """构建并编译 StoryWeaver 的核心小说生成流"""

    # 1. 初始化状态图
    workflow = StateGraph(TomatoNovelState)

    # 2. 注册所有核心节点 (🌟 包含新加入的 Macro_Planner)
    workflow.add_node("Macro_Planner", macro_planner_node)
    workflow.add_node("Plot_Planner", plot_planner_node)
    workflow.add_node("Chapter_Writer", chapter_writer_node)
    workflow.add_node("Editor", continuity_editor_node)
    workflow.add_node("Human_Review", human_review_node)
    workflow.add_node("Memory_Keeper", memory_keeper_node)

    # 3. 🌟 定义常规流转边：增加了宏观规划的层级
    workflow.add_edge(START, "Macro_Planner")
    workflow.add_edge("Macro_Planner", "Plot_Planner")
    workflow.add_edge("Plot_Planner", "Chapter_Writer")
    workflow.add_edge("Chapter_Writer", "Editor")

    # 4. === 第一阶段：内部 AI 互搏循环 (写与审的博弈) ===
    # Editor 审完后，根据结果分发
    workflow.add_conditional_edges("Editor",editor_router)

    # 5. === 第二阶段：外部人类决断循环 (一键入库还是大修打回) ===
    # Human Review 决策后，根据人类的意愿分发
    workflow.add_conditional_edges("Human_Review",human_review_router)

    # 6. 入库完结，准备进入下一章节的循环
    workflow.add_edge("Memory_Keeper", END)

    return workflow