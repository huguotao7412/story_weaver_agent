# app/agents/volume_planner.py
import json
from typing import Dict, Any

from app.agents.base import BaseAgent
from app.core.llm_factory import get_llm
from app.memory.kv_tracker import AsyncKVTracker
from app.memory.rag_engine import RAGEngine
from app.agents.registry import register
from protocols.a2a_schemas import VolumePhases

import asyncio


class VolumePlannerAgent(BaseAgent):
    name = "Volume_Planner"
    prompt_file = "volume_planner.yaml"

    async def execute(self, state: dict) -> Dict[str, Any]:
        current_chapter_num = state.get("current_chapter_num", 1)
        current_book_id = state.get("book_id", "default_book")

        current_volume_num = (current_chapter_num - 1) // 50 + 1
        is_new_volume = (current_chapter_num == 1) or ((current_chapter_num - 1) % 50 == 0)

        if state.get("is_volume_initialized", False) and not is_new_volume:
            return {"is_volume_initialized": True}

        print(f"\U0001f4dc [Volume-Planner] 触发第 {current_volume_num} 卷规划！正在提取底层状态进行软修正...", flush=True)

        llm = get_llm(temperature=0.3)

        tracker = AsyncKVTracker(book_id=current_book_id)
        await tracker.init_db()

        book_outline = await tracker.get_temp_context("book_outline", "暂无总纲")
        kv_snapshot = await tracker.get_world_bible_snapshot()

        prev_volumes_text = "（这是本书第一卷，暂无前卷剧情）"
        if current_volume_num > 1:
            summaries = await tracker.get_volume_summaries(1, current_volume_num - 1)
            if summaries:
                prev_volumes_text = "\n\n".join(summaries)

        try:
            messages = self.load_prompt(
                current_volume_num=current_volume_num,
                book_outline=book_outline,
                kv_snapshot=kv_snapshot,
                previous_volume_summaries=prev_volumes_text
            )
            phase_result: VolumePhases = await self.safe_json_invoke(llm, messages, VolumePhases)
            phase_json = json.dumps(phase_result.model_dump(), ensure_ascii=False, indent=2)

            if current_chapter_num > 1 and is_new_volume:
                print("\U0001f9f9 [Volume-Planner] 动态新卷大纲生成成功！正在安全清理上一卷的局部 RAG 细节...")
                try:
                    await asyncio.to_thread(RAGEngine(book_id=current_book_id).reset_volume_store)
                except Exception as e:
                    print(f"⚠️ RAG 清理异常: {e}")

            await tracker.save_temp_context("volume_phases", phase_json)
            return {"is_volume_initialized": True}
        except Exception as e:
            print(f"❌ [Volume-Planner] 分卷大纲生成失败: {e}")
            return {"is_volume_initialized": False}


@register("volume_planner")
async def volume_planner_node(state: dict) -> Dict[str, Any]:
    agent = VolumePlannerAgent()
    return await agent.execute(state)
