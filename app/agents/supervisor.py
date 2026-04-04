# 总管节点：负责任务分发、熔断、调用人类干预接口
# 👑 Supervisor / Human-Review (总管与人类在环)
# 职责：统筹节点流转，接收人类（总编）的大修批注意图并强行覆盖（Human Override）。
# 借鉴：principia-ai/WriteHERE 的递归规划与人工干预机制
# app/agents/supervisor.py

from typing import Dict, Any
from langchain_core.messages import HumanMessage, AIMessage


def human_review_node(state: dict) -> Dict[str, Any]:
    """
    👑 Human-Review Node (人类在环/总编决策)

    【机制说明】：
    在 LangGraph 的定义中，这个节点是被设置为 `interrupt_before=["Human_Review"]` 的。
    这意味着：当代码执行到准备进入本节点时，引擎会**强制挂起 (Pause)**。

    此时，控制权交还给前端（如 Streamlit UI）：
    1. 人类阅读左侧草稿。
    2. 人类在右侧面板点击【批准】或【打回重写】，并填写 `human_feedback`。
    3. 前端调用 `graph.update_state()` 将人类的决定注入 State。
    4. 前端调用 `graph.invoke(None)` 恢复执行，此时才会真正跑进下面这段代码！
    """
    print("\n" + "=" * 50)
    print("👑 [Supervisor] 收到来自人类总编的最高权限指令...")

    # 获取人类注入的决策状态和批注反馈
    status = state.get("human_approval_status", "PENDING").upper()
    feedback = state.get("human_feedback", "")
    direct_edits = state.get("direct_edits", "")
    chapter_num = state.get("current_chapter_num", 1)

    draft_updates = {}
    if direct_edits and direct_edits.strip() != "":
        print("👑 [Supervisor] 检测到总编的手动批改文本，正在强行覆盖原系统草稿...")
        draft_updates["draft_content"] = direct_edits

    # 1. 人类直接批准入库
    if status == "APPROVED":
        msg = AIMessage(content="[Supervisor] 总编已批准该章节入库。", name="Supervisor")
        print(f"✅ [Supervisor] 总编已批准第 {chapter_num} 章定稿！流转至 Memory-Keeper。")
        return {
            "human_approval_status": "APPROVED",
            "human_feedback": "",
            "direct_edits": "",  # 清空历史状态
            "editor_comments": "PASS",
            "internal_revision_count": 0,  # 重置打回计数器
            "messages": [msg],
            **draft_updates  # 注入修改后的草稿
        }

    # 2. 人类打回并附加强指令覆盖 (Human Override)
    elif status == "REJECTED":
        if not feedback:
            feedback = "草稿质量不佳，请主笔重新构思并重写本章。"

        override_msg = HumanMessage(
            content=f"【人类总编最高指令】：{feedback}",
            name="Human_Editor"
        )

        # 借鉴 WriteHERE 的递归规划：不仅是“打回”，而是将人类逻辑注入下一次生成
        return {
            "human_approval_status": "REJECTED",
            "human_feedback": feedback,
            # 将内部 AI 审查的状态重置，因为现在是人类主导的重写逻辑
            "editor_comments": "HUMAN_OVERRIDE_TRIGGERED",
            "messages": [override_msg]
        }

    # 3. 异常状态兜底（比如没有经过 UI 交互直接触发了）
    else:
        print("⚠️ [Supervisor] 未检测到明确的人类决策，默认挂起。")
        return {
            "human_approval_status": "PENDING"
        }