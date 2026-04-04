# 核心图编排：定义节点流转、双向循环与中断断点
# 🕸️ 核心工作流图编排：LangGraph 两段式路由与人类在环
# app/agents/graph.py

from langgraph.graph import StateGraph, START, END
from typing import Literal

from langgraph.checkpoint.memory import MemorySaver

# 导入核心状态结构
from app.core.state import TomatoNovelState

# 导入所有 Worker Nodes
from app.agents.workers.plot_planner import plot_planner_node
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
    else:
        print("🔀 [Router] 内部审查未通过，打回主笔节点返工。")
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

    # 2. 注册所有核心节点
    workflow.add_node("Plot_Planner", plot_planner_node)
    workflow.add_node("Chapter_Writer", chapter_writer_node)
    workflow.add_node("Editor", continuity_editor_node)
    workflow.add_node("Human_Review", human_review_node)
    workflow.add_node("Memory_Keeper", memory_keeper_node)

    # 3. 定义常规流转边 (线性推进)
    workflow.add_edge(START, "Plot_Planner")
    workflow.add_edge("Plot_Planner", "Chapter_Writer")
    workflow.add_edge("Chapter_Writer", "Editor")

    # 4. === 第一阶段：内部 AI 互搏循环 (写与审的博弈) ===
    # Editor 审完后，根据结果分发
    workflow.add_conditional_edges(
        "Editor",
        editor_router
    )

    # 5. === 第二阶段：外部人类决断循环 (一键入库还是大修打回) ===
    # Human Review 决策后，根据人类的意愿分发
    workflow.add_conditional_edges(
        "Human_Review",
        human_review_router
    )

    # 6. 入库完结，准备进入下一章节的循环
    workflow.add_edge("Memory_Keeper", END)
    memory = MemorySaver()

    # 7. 🌟 编译图并设置“人类干预断点 (Breakpoints)”
    # 这是最核心的一步：在执行到 Human_Review 节点前，系统强制挂起，等待前端 UI 注入人类的新状态
    compiled_graph = workflow.compile(
        checkpointer=memory,
        interrupt_before=["Human_Review"])

    return compiled_graph


# 导出编译好的实例供 API / CLI 调用
storyweaver_app = build_workflow()