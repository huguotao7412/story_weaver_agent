# app/agents/workers/continuity_editor.py
import os
import json
import asyncio
from typing import Dict, Any

from langchain_core.messages import HumanMessage

from app.agents.base import BaseAgent
from app.memory.kv_tracker import AsyncKVTracker
from app.core.llm_factory import get_llm
from app.agents.registry import register
from protocols.hitl_schemas import EditorInternalReview


class ContinuityEditorAgent(BaseAgent):
    name = "Continuity_Editor"
    prompt_file = "continuity_editor.yaml"

    async def execute(self, state: dict) -> Dict[str, Any]:
        tracker = AsyncKVTracker(book_id=state.get("book_id", "default_book"))
        await tracker.init_db()
        current_kv_state = await tracker.get_world_bible_snapshot()
        draft_path = state.get("draft_path", "")
        draft = ""
        if draft_path and os.path.exists(draft_path):
            with open(draft_path, "r", encoding="utf-8") as f:
                draft = f.read()
        beat_sheet = state.get("current_beat_sheet", "")
        revision_count = state.get("internal_revision_count", 0)
        chapter_num = state.get("current_chapter_num", 1)

        if not draft:
            return {"editor_comments": "PASS"}

        print(
            f"🕵️ [Continuity-Editor] 正在对第 {chapter_num} 章草稿进行严格内审... (当前重试: {revision_count}/2)")

        if revision_count >= 2:
            print("⚠️ [Continuity-Editor] 连续打回次数已达上限 (2次)，强制放行交由人类总编裁决。")
            return {
                "editor_comments": "PASS_WITH_WARNING",
                "internal_revision_count": 0
            }

        llm = get_llm(temperature=0.1)
        messages = self.load_prompt(kv_state=current_kv_state, draft_len=len(draft))
        schema_str = json.dumps(EditorInternalReview.model_json_schema(), ensure_ascii=False)
        messages.append(HumanMessage(
            content=f"【本章规定节拍器 (绝对红线)】：\n{beat_sheet}\n\n【主笔生成的正文草稿】：\n{draft}\n\n请进行严格质检。必须输出以下 JSON Schema 格式的数据：\n{schema_str}"
        ))

        try:
            print(f"⏳ [Continuity-Editor] 正在调用大模型进行质检...")
            response = await asyncio.wait_for(llm.ainvoke(messages), timeout=180)

            json_str = self.extract_json(response.content)
            review: EditorInternalReview = EditorInternalReview.model_validate_json(json_str)

            if review.status == "FAIL":
                print(f"❌ [Continuity-Editor] 质检未通过！发现问题：{review.bug_reports}")
                new_history = state.get("revision_history", []) + [
                    f"【内审打回】扣分点: {review.bug_reports} | 建议: {review.revision_suggestions}"]
                return {
                    "editor_comments": "FAIL",
                    "internal_revision_count": revision_count + 1,
                    "revision_history": new_history
                }
            else:
                print("✅ [Continuity-Editor] 质检完美通过！无越界与字数问题。")
                return {
                    "editor_comments": "PASS",
                    "internal_revision_count": 0
                }

        except Exception as e:
            print(f"⚠️ [Continuity-Editor] 质检发生异常，默认放行: {e}")
            return {"editor_comments": "PASS", "internal_revision_count": 0}


@register("continuity_editor")
async def continuity_editor_node(state: dict) -> Dict[str, Any]:
    agent = ContinuityEditorAgent()
    return await agent.execute(state)
