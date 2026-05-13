# app/agents/chapter_planner.py
import json
import asyncio
from typing import Dict, Any

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from app.agents.base import BaseAgent
from app.core.llm_factory import get_llm
from app.memory.kv_tracker import AsyncKVTracker
from app.memory.rag_engine import RAGEngine
from app.agents.registry import register
from app.agents.workers.all_planner import get_focused_volume_phases, get_focused_phase_chapters
from protocols.a2a_schemas import ChapterOutline


class RAGQueryPlan(BaseModel):
    """动态决定三层 RAG 检索策略"""
    optimized_query: str = Field(
        description="从当前章梗概中提取的核心关键词（如特定人名、地名、功法），用空格分隔，滤除无用废话")
    k_global: int = Field(
        description="全局设定库检索量(0-3)。若涉及世界观揭秘、大境界突破、远古大伏笔，请给2-3；纯日常给0。")
    k_volume: int = Field(
        description="分卷主线库检索量(0-3)。若涉及本卷核心反派冲突、长线任务推进，请给2-3；否则给1。")
    k_phase: int = Field(
        description="近期细节库检索量(1-4)。若正在进行连贯的战斗、动作接续、紧凑对话，请给3-4；新开地图或时间跳跃给1。")


class ChapterPlannerAgent(BaseAgent):
    name = "Chapter_Planner"
    prompt_file = "chapter_planner.yaml"

    async def execute(self, state: dict) -> Dict[str, Any]:
        current_chapter_num = state.get("current_chapter_num", 1)
        current_book_id = state.get("book_id", "default_book")
        print(f"\U0001f4cd [Chapter-Planner] 正在严格对齐本期十章梗概，拆解第 {current_chapter_num} 章节拍器...", flush=True)

        latest_user_instruction = state.get("user_input", "")

        human_override_instruction = ""
        if latest_user_instruction and latest_user_instruction.strip() and latest_user_instruction.strip() not in [
            "请按网文套路推进", ""]:
            human_override_instruction = (
                f"\U0001f525【人类上帝指令 (God Command Override)】\U0001f525\n"
                f"人类总编刚刚下达了本章的特定诉求：\n《{latest_user_instruction}》\n"
                f"\U0001f6a8 警告：无论本章原本处于什么心流节奏（舒缓/高潮/悬疑），你都【必须绝对优先】满足总编的上述指令！系统节奏规则必须无条件让位于人类指令！\n"
                f"====================================================\n"
            )

        llm = get_llm(temperature=0.2)
        world_bible = state.get("world_bible_context", "")
        phase_chapters = state.get("current_phase_chapters", "")

        raw_volume_phases = state.get("current_volume_phases", "（暂无分卷大纲）")
        focused_volume_phases = get_focused_volume_phases(raw_volume_phases, current_chapter_num)

        raw_phase_chapters = state.get("current_phase_chapters", "（暂无单期大纲）")
        focused_phase_chapters = get_focused_phase_chapters(raw_phase_chapters, current_chapter_num)

        prev_ending_text = state.get("previous_chapter_ending", "")
        if prev_ending_text:
            formatted_prev_ending = f"以下是上一章最后500字原文：\n《...{prev_ending_text}》\n（请让本章的第一个节拍紧接着这个动作或对话开始）"
        else:
            formatted_prev_ending = "（全书或新卷首章，暂无上一章结尾，请正常开局）"

        query_str = ""

        try:
            tracker = AsyncKVTracker(book_id=current_book_id)
            await tracker.init_db()
            current_map = await tracker.get_global_map()
            power_rules = await tracker.get_power_system_rules()

            try:
                rag_router_llm = get_llm(temperature=0.1)
                rewriter_prompt = (
                    f"你是一个RAG检索路由专家。当前准备写第 {current_chapter_num} 章。\n"
                    f"【本期大纲参考】:\n{phase_chapters}\n\n"
                    f"任务：请分析当前章的剧情重点，提取精准的关键词，并动态分配三层数据库的检索额度 K 值。\n"
                    f"请直接输出一个完整的 JSON 对象，不要包裹在 markdown 代码块中，不要添加任何解释性文本。"
                )
                rag_plan: RAGQueryPlan = await self.safe_json_invoke(
                    rag_router_llm, [HumanMessage(content=rewriter_prompt)],
                    RAGQueryPlan, max_retries=2, timeout=60
                )
                query_str = rag_plan.optimized_query

                print(
                    f"   [\U0001f50d RAG 智能路由] 关键词: {rag_plan.optimized_query} | K值分配: Global={rag_plan.k_global}, Volume={rag_plan.k_volume}, Phase={rag_plan.k_phase}")

                rag_engine = RAGEngine(book_id=current_book_id)
                history_context = await asyncio.to_thread(
                    rag_engine.retrieve_context,
                    query=rag_plan.optimized_query,
                    k_global=rag_plan.k_global,
                    k_volume=rag_plan.k_volume,
                    k_phase=rag_plan.k_phase
                )
            except Exception as e:
                print(f"⚠️ [Query-Rewriter 异常，降级为默认模糊检索]: {e}")
                query_str = ""
                rag_engine = RAGEngine(book_id=current_book_id)
                history_context = await asyncio.to_thread(
                    rag_engine.retrieve_context,
                    query=phase_chapters,
                    k_global=1,
                    k_volume=2,
                    k_phase=2
                )

            filter_keywords = query_str.split() if query_str else []
            current_kv_state = await tracker.get_world_bible_snapshot(filter_entities=filter_keywords)

            unresolved_threads = await tracker.get_active_threads_snapshot(current_map=current_map,
                                                                           query_keywords=query_str)
            current_kv_state += f"\n\n{unresolved_threads}"

        except Exception as e:
            print(f"⚠️ [状态提取异常]: {e}")
            current_kv_state, history_context = "（暂无角色与伏笔状态）", "（暂无历史剧情）"
            power_rules = "（暂无战力设定）"

        idx = (current_chapter_num - 1) % 10
        if idx in [0, 1, 2]:
            climax_rule = "   - 【舒缓/日常期】无需强求打脸，重点展现探索、情报收集和日常收获的乐趣。"
            cliffhanger_rule = "   - 【期待钩子】绝对禁止强行制造生死危机！结尾请设置一个期待感，如发现新事物、实力的细微变化，或轻松的互动。"
        elif idx in [3, 4, 5]:
            climax_rule = "   - 【蓄力/探索期】包含小规模的拉扯、试探或智斗展现。"
            cliffhanger_rule = "   - 【悬疑钩子】结尾请设置一个悬念，如即将推开密室的门、反派的一句阴谋暗示、或即将爆发冲突的前兆。"
        elif idx in [6, 7, 8]:
            climax_rule = "   - 【爆发/高潮期】网文公式约束（强制）：必须包含至少一个【爽点/打脸/装逼】环节，干脆利落！"
            cliffhanger_rule = "   - 【断章狗钩子】本章核心矛盾爆发！结尾必须卡在最危险的生死瞬间或底牌揭晓的一刻！"
        else:
            climax_rule = "   - 【结算/余波期】核心是展现高潮过后的【满足感】和清点战利品的暗爽，无需战斗。"
            cliffhanger_rule = "   - 【满足钩子】高潮已过，绝对禁止在结尾引出新敌人！结尾必须是战利品清点完毕后的笑容、众人对主角的惊叹，或遥望新目标的憧憬。"

        summary_list = state.get("recent_chapters_summary", [])
        recent_chapters_summary = "\n\n".join([f"【N-{len(summary_list) - i} 前情脉络】:\n{text}" for i, text in
                                               enumerate(summary_list)]) if summary_list else "（暂无前情提要）"

        messages = self.load_prompt(
            chapter_num=current_chapter_num,
            human_override_instruction=human_override_instruction,
            previous_chapter_ending=formatted_prev_ending,
            recent_chapters_summary=recent_chapters_summary,
            focused_phase_chapters=focused_phase_chapters,
            power_system_rules=power_rules,
            world_bible=world_bible,
            volume_phases=focused_volume_phases,
            kv_state=current_kv_state,
            history_context=history_context,
            climax_rule=climax_rule,
            cliffhanger_rule=cliffhanger_rule
        )

        try:
            planner_response: ChapterOutline = await self.safe_json_invoke(llm, messages, ChapterOutline)
            beat_sheet_json = json.dumps(planner_response.model_dump(), ensure_ascii=False, indent=2)

            return {
                "current_beat_sheet": beat_sheet_json,
                "rag_history_context": history_context
            }
        except Exception as e:
            print(f"❌ [Chapter-Planner] 节拍器生成失败: {e}")
            return {"current_beat_sheet": "（大纲生成异常，请主笔自由发挥）"}


@register("chapter_planner")
async def chapter_planner_node(state: dict) -> Dict[str, Any]:
    agent = ChapterPlannerAgent()
    return await agent.execute(state)
