# app/agents/book_planner.py
import json
import asyncio
from typing import Dict, Any

from langchain_core.messages import HumanMessage

from app.agents.base import BaseAgent
from app.core.llm_factory import get_llm
from app.memory.kv_tracker import AsyncKVTracker
from app.memory.rag_engine import RAGEngine
from app.agents.registry import register
from protocols.a2a_schemas import BookOutline


class BookPlannerAgent(BaseAgent):
    name = "Book_Planner"
    prompt_file = "book_planner.yaml"

    async def execute(self, state: dict) -> Dict[str, Any]:
        current_book_id = state.get("book_id", "default_book")

        if state.get("is_book_initialized", False):
            return {"is_book_initialized": True}

        print(f"\U0001f4da [Book-Planner] 检测到全新长篇 (Book ID: {current_book_id})，正在初始化《全书总纲》与世界观...", flush=True)
        llm = get_llm(temperature=0.3)

        tracker = AsyncKVTracker(book_id=current_book_id)
        await tracker.init_db()

        user_input = state.get("user_input", "请按网文套路推进")
        world_bible_preset = await tracker.get_temp_context("world_bible", "")

        if world_bible_preset:
            print("   [Book-Planner] 检测到作者预设的《世界观设定》，将以此为基准推演大纲...", flush=True)
            prompt_content = (
                f"【作者预设的权威世界观（请绝对遵循，不要擅自修改设定的规则与境界）】：\n{world_bible_preset}\n\n"
                f"【本次剧情脑洞/指令】：{user_input}\n\n"
                f"任务：请基于上述权威世界观，推演出【全书十卷大纲】，并将预设世界观整理润色后填入 world_bible 字段中返回。"
            )
        else:
            print("   [Book-Planner] 无预设设定，将根据脑洞从零生成世界观...", flush=True)
            prompt_content = f"【用户初始脑洞】：{user_input}\n请发挥创意，从零构建《世界观圣经》并规划【全书十卷大纲】。"

        try:
            messages = self.load_prompt()
            messages.append(HumanMessage(content=prompt_content))
            book_result: BookOutline = await self.safe_json_invoke(llm, messages, BookOutline)
            book_json = json.dumps(book_result.model_dump(), ensure_ascii=False, indent=2)

            await tracker.set_power_system_rules(book_result.power_system_rules)

            try:
                rag_engine = RAGEngine(book_id=current_book_id)
                await asyncio.to_thread(rag_engine.insert_world_bible,
                                        [{"title": "全书世界观与总纲", "content": book_json}])
                print("✅ [Book-Planner] 《全书总纲》已成功灌入全局 RAG 向量空间。")
            except Exception as e:
                print(f"⚠️ [Book-Planner] RAG 持久化异常: {e}")

            await tracker.save_temp_context("book_outline", book_json)
            await tracker.save_temp_context("world_bible", book_result.world_lore)

            return {"is_book_initialized": True}
        except Exception as e:
            print(f"❌ [Book-Planner] 总纲初始化失败: {e}")
            return {"is_book_initialized": False}


@register("book_planner")
async def book_planner_node(state: dict) -> Dict[str, Any]:
    agent = BookPlannerAgent()
    return await agent.execute(state)
