# app/agents/phase_planner.py
import json
from typing import Dict, Any

from app.agents.base import BaseAgent
from app.core.llm_factory import get_llm
from app.memory.kv_tracker import AsyncKVTracker
from app.memory.rag_engine import RAGEngine
from app.agents.registry import register
from app.agents.workers.all_planner import get_focused_volume_phases
from protocols.a2a_schemas import PhaseChapters

import asyncio


class PhasePlannerAgent(BaseAgent):
    name = "Phase_Planner"
    prompt_file = "phase_planner.yaml"

    async def execute(self, state: dict) -> Dict[str, Any]:
        phase_chapters = state.get("current_phase_chapters", "")
        current_chapter_num = state.get("current_chapter_num", 1)
        current_book_id = state.get("book_id", "default_book")

        is_new_phase = (current_chapter_num == 1) or ((current_chapter_num - 1) % 10 == 0)

        if phase_chapters and phase_chapters.strip() != "" and not is_new_phase:
            return {"is_phase_initialized": True}

        current_volume_num = (current_chapter_num - 1) // 50 + 1
        absolute_phase_num = (current_chapter_num - 1) // 10 + 1
        current_phase_index = ((current_chapter_num - 1) % 50) // 10
        current_phase_name = f"第 {current_phase_index + 1} 期"
        start_phase_of_volume = (current_volume_num - 1) * 5 + 1

        print(f"\U0001f4d1 [Phase-Planner] 触发跨期推演！当前进入【{current_phase_name}】，正在提取本卷真实剧情碎片...", flush=True)

        llm = get_llm(temperature=0.2)
        world_bible = state.get("world_bible_context", "")

        raw_volume_phases = state.get("current_volume_phases", "")
        focused_volume_phases = get_focused_volume_phases(raw_volume_phases, current_chapter_num)

        tracker = AsyncKVTracker(book_id=current_book_id)
        await tracker.init_db()
        kv_snapshot = await tracker.get_world_bible_snapshot()

        prev_phases_text = "（本卷刚开始，暂无本卷的前期剧情回顾）"
        if absolute_phase_num > start_phase_of_volume:
            summaries = await tracker.get_phase_summaries(start_phase_of_volume, absolute_phase_num - 1)
            if summaries:
                prev_phases_text = "\n\n".join(summaries)

        try:
            rag_engine = RAGEngine(book_id=current_book_id)
            history_context = await asyncio.to_thread(
                rag_engine.retrieve_context, query=focused_volume_phases, k_global=1, k_volume=2, k_phase=1
            )
        except:
            history_context = "（暂无历史）"

        try:
            messages = self.load_prompt(
                world_bible=world_bible,
                volume_phases=focused_volume_phases,
                history_context=history_context,
                kv_snapshot=kv_snapshot,
                previous_phase_summaries=prev_phases_text,
                current_phase_name=current_phase_name
            )
            chapters_result: PhaseChapters = await self.safe_json_invoke(llm, messages, PhaseChapters)
            chapters_json = json.dumps(chapters_result.model_dump(), ensure_ascii=False, indent=2)

            if current_chapter_num > 1 and is_new_phase:
                print("\U0001f9f9 [Phase-Planner] 动态新期推演成功！正在安全清理上一期的微观 RAG 碎片...")
                try:
                    await asyncio.to_thread(RAGEngine(book_id=current_book_id).reset_phase_store)
                except Exception as e:
                    pass

            return {"current_phase_chapters": chapters_json, "is_phase_initialized": True}
        except Exception as e:
            print(f"❌ [Phase-Planner] 单期大纲生成失败: {e}")
            return {"is_phase_initialized": False}


@register("phase_planner")
async def phase_planner_node(state: dict) -> Dict[str, Any]:
    agent = PhasePlannerAgent()
    return await agent.execute(state)
