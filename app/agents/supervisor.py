# 总管节点：负责任务分发、熔断、调用人类干预接口
# 👑 Supervisor / Human-Review (总管与人类在环)
# 职责：统筹节点流转，接收人类（总编）的大修批注意图并强行覆盖（Human Override）。
# 借鉴：principia-ai/WriteHERE 的递归规划与人工干预机制
# app/agents/supervisor.py

from typing import Dict, Any


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
    chapter_num = state.get("current_chapter_num", 1)

    # 1. 人类直接批准入库
    if status == "APPROVED":
        print(f"✅ [Supervisor] 总编已批准第 {chapter_num} 章定稿！流转至 Memory-Keeper 进行持久化。")
        return {
            "human_approval_status": "APPROVED",
            # 清空上一轮的反馈和内部报错，保持 State 干净
            "human_feedback": "",
            "editor_comments": "PASS"
        }

    # 2. 人类打回并附加强指令覆盖 (Human Override)
    elif status == "REJECTED":
        if not feedback:
            feedback = "草稿质量不佳，请主笔重新构思并重写本章。"

        print(f"🔥 [Supervisor] 触发最高级别打回重写！")
        print(f"   [批注指令]: {feedback}")
        print(f"   流转被截断，已将人类意图作为 Override Prompt 注入，准备重新唤醒 Chapter-Writer。")

        # 借鉴 WriteHERE 的递归规划：不仅是“打回”，而是将人类逻辑注入下一次生成
        return {
            "human_approval_status": "REJECTED",
            "human_feedback": feedback,
            # 将内部 AI 审查的状态重置，因为现在是人类主导的重写逻辑
            "editor_comments": "HUMAN_OVERRIDE_TRIGGERED"
        }

    # 3. 异常状态兜底（比如没有经过 UI 交互直接触发了）
    else:
        print("⚠️ [Supervisor] 未检测到明确的人类决策，默认挂起。")
        return {
            "human_approval_status": "PENDING"
        }