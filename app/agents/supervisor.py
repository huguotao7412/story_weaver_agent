# app/agents/supervisor.py
import os
import uuid
from typing import Dict, Any

from langchain_core.messages import AIMessage

from app.agents.base import BaseAgent
from app.agents.registry import register


class HumanReviewAgent(BaseAgent):
    name = "Human_Review"
    prompt_file = "_unused.yaml"  # Human_Review has no LLM prompt

    def load_prompt(self, **kwargs):
        return []  # No prompt needed for human review

    async def execute(self, state: dict) -> Dict[str, Any]:
        print("\n" + "=" * 50)
        print("👑 [Supervisor] 收到来自人类总编的最高权限指令...")

        status = state.get("human_approval_status", "PENDING").upper()
        feedback = state.get("human_feedback", "")
        direct_edits = state.get("direct_edits", "")
        chapter_num = state.get("current_chapter_num", 1)
        draft_path = state.get("draft_path", "")
        editor_status = state.get("editor_comments", "")

        if direct_edits and direct_edits.strip() != "":
            print("👑 [Supervisor] 检测到总编的手动批改文本，正在强行覆盖原系统本地草稿...")
            if draft_path:
                os.makedirs(os.path.dirname(draft_path), exist_ok=True)
                with open(draft_path, "w", encoding="utf-8") as f:
                    f.write(direct_edits)

        if status == "APPROVED":
            msg = AIMessage(content="[Supervisor] 总编已批准该章节入库。", name="Supervisor", id=str(uuid.uuid4()))
            print(f"✅ [Supervisor] 总编已批准第 {chapter_num} 章定稿！流转至 Memory-Keeper。")
            return {
                "human_approval_status": "APPROVED",
                "human_feedback": "",
                "direct_edits": "",
                "editor_comments": "PASS",
                "internal_revision_count": 0,
            }

        elif status == "REJECTED":
            if not feedback:
                feedback = "草稿质量不佳，请主笔重新构思并重写本章。"

            new_history = state.get("revision_history", []) + [f"【总编打回】: {feedback}"]
            return {
                "human_approval_status": "REJECTED",
                "human_feedback": feedback,
                "editor_comments": "HUMAN_OVERRIDE_TRIGGERED",
                "revision_history": new_history
            }

        elif editor_status == "PASS_WITH_WARNING" and status == "PENDING":
            print("⚠️ [Supervisor] 接收到内审组的强行放行信号，等待总编最终裁定。")
            return {
                "human_approval_status": "PENDING"
            }

        else:
            print("⚠️ [Supervisor] 未检测到明确的人类决策，默认挂起。")
            return {
                "human_approval_status": "PENDING"
            }


@register("human_review")
async def human_review_node(state: dict) -> Dict[str, Any]:
    agent = HumanReviewAgent()
    return await agent.execute(state)
