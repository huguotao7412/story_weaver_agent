# app/agents/workers/all_planner.py

import json
from typing import Dict, Any
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.core.llm_factory import get_llm
from app.core.config import settings
from app.memory.kv_tracker import KVTracker
from app.memory.rag_engine import RAGEngine

from protocols.a2a_schemas import BookOutline, VolumePhases, PhaseChapters, ChapterOutline

# ==========================================
# 🧠 四层提示词定义区
# ==========================================

# 1. 第一层：全书总纲 (10卷)
LAYER1_BOOK_PROMPT = """你是一个白金级网文【全书总架构师】。
你的任务是基于用户的初始脑洞，构建《世界观圣经》并规划【全书十卷】的总脉络（预计百万字规模）。

请包含：
1. 《世界观圣经》：核心设定、力量体系、主角初始人设与终极目标。
2. 《全书十卷大纲》：规划 10 个分卷的名字和核心任务（主角从弱小到巅峰的成长轨迹）。
"""

# 2. 第二层：分卷三期 (前、中、后)
LAYER2_VOLUME_PROMPT = """你是一个资深网文【分卷大纲主编】。
你的任务是提取《全书总纲》中【第 {current_volume_num} 卷】的核心目标，将其严格切分为“前、中、后”三期。

【全局世界观与十卷总纲】：
{book_outline}

要求：
- 前期（约10章）：起与承，引入本卷新地图/新矛盾，主角遭遇打压或接到任务。
- 中期（约10章）：转与蓄力，主角寻找破局之法，获得关键道具或实力突破。
- 后期（约10章）：合与高潮，终极对决，打脸反派，收获战利品并引出下一卷钩子。
"""

# 3. 第三层：单期十章 (10章)
LAYER3_PHASE_PROMPT = """你是一个精细的网文【单期统筹编剧】。
你的任务是基于当前卷的【{current_phase_name}】目标，规划出具体的【十章】剧情梗概。

【全局世界观】：
{world_bible}
【本卷三期规划】：
{volume_phases}
【🌟 RAG 历史伏笔参考】：
{history_context}

要求：
每一章只需一两句话的核心剧情梗概，必须保证这十章的剧情连贯，且刚好完成本期指派的剧情任务。
"""

# 4. 第四层：单章节拍 (3-5节拍)
LAYER4_CHAPTER_PROMPT = """你是一个极其严苛的番茄【执行主编 / 节拍拆解员】。
基于《十章剧情梗概》中对第 {chapter_num} 章的规划，为本章拆解出详细的 3-5 个“单章节拍器（Beat Sheet）”。

【当前世界观与设定】：
{world_bible}
【👑本卷核心大目标 (防偏题必备)】：
{volume_phases}
【本期十章梗概】：
{phase_chapters}
【🌟当前人物与物品状态快照 (KV Database)】：
{kv_state}
【🌟相关历史剧情与伏笔参考 (RAG Database)】：
{history_context}

要求：
1. 宏观对齐：本章节拍必须吻合大纲指派的任务，且绝对不能偏离【本卷核心大目标】。
2. 网文公式约束（强制）：必须包含至少一个【爽点/打脸/装逼】环节。
{cliffhanger_rule}
"""

class RAGQueryPlan(BaseModel):
    """动态决定三层 RAG 检索策略"""
    optimized_query: str = Field(description="从当前章梗概中提取的核心关键词（如特定人名、地名、功法），用空格分隔，滤除无用废话")
    k_global: int = Field(description="全局设定库检索量(0-3)。若涉及世界观揭秘、大境界突破、远古大伏笔，请给2-3；纯日常给0。")
    k_volume: int = Field(description="分卷主线库检索量(0-3)。若涉及本卷核心反派冲突、长线任务推进，请给2-3；否则给1。")
    k_phase: int = Field(description="近期细节库检索量(1-4)。若正在进行连贯的战斗、动作接续、紧凑对话，请给3-4；新开地图或时间跳跃给1。")

# ==========================================
# 🗺️ 节点一：全书总架构师 (Book Planner)
# ==========================================
async def book_planner_node(state: dict) -> Dict[str, Any]:
    """负责初始化世界观，并生成全书 10 卷大纲"""
    book_outline = state.get("book_outline_context", "")
    current_book_id = state.get("book_id", "default_book")  # 🌟 提取书名 ID

    if book_outline and book_outline.strip() != "":
        return {}  # 已存在则直接跳过

    print(f"📚 [Book-Planner] 检测到全新长篇 (Book ID: {current_book_id})，正在初始化《全书总纲》与世界观...")
    llm = get_llm(model_type="main", temperature=0.3)
    user_input = state.get("messages", [HumanMessage(content="请按网文套路推进")])[-1].content

    world_bible_preset = state.get("world_bible_context", "")

    if world_bible_preset:
        print("   [Book-Planner] 检测到作者预设的《世界观设定》，将以此为基准推演大纲...")
        prompt_content = (
            f"【作者预设的权威世界观（请绝对遵循，不要擅自修改设定的规则与境界）】：\n{world_bible_preset}\n\n"
            f"【本次剧情脑洞/指令】：{user_input}\n\n"
            f"任务：请基于上述权威世界观，推演出【全书十卷大纲】，并将预设世界观整理润色后填入 world_bible 字段中返回。"
        )
    else:
        print("   [Book-Planner] 无预设设定，将根据脑洞从零生成世界观...")
        prompt_content = f"【用户初始脑洞】：{user_input}\n请发挥创意，从零构建《世界观圣经》并规划【全书十卷大纲】。"

    structured_llm = llm.with_structured_output(BookOutline)
    messages = [
        SystemMessage(content=LAYER1_BOOK_PROMPT),
        HumanMessage(content=prompt_content)
    ]

    try:
        book_result: BookOutline = await structured_llm.ainvoke(messages)
        book_json = json.dumps(book_result.model_dump(), ensure_ascii=False, indent=2)

        # 🌟 知识库防漏水：第一时间将世界观灌入全局 RAG
        try:
            rag_engine = RAGEngine(book_id=current_book_id)  # 🌟 隔离实例
            rag_engine.insert_world_bible([{"title": "全书世界观与总纲", "content": book_json}])
            print("✅ [Book-Planner] 《全书总纲》已成功灌入全局 RAG 向量空间。")
        except Exception as e:
            print(f"⚠️ [Book-Planner] RAG 持久化异常: {e}")

        return {"book_outline_context": book_json, "world_bible_context": book_result.world_bible}
    except Exception as e:
        print(f"⚠️ [Book-Planner] 异常: {e}")
        return {}


# ==========================================
# 🗺️ 节点二：分卷三期规划师 (Volume Planner)
# ==========================================
async def volume_planner_node(state: dict) -> Dict[str, Any]:
    """负责将当前卷切分为前、中、后三期"""
    volume_phases = state.get("current_volume_phases", "")
    current_chapter_num = state.get("current_chapter_num", 1)
    current_book_id = state.get("book_id", "default_book")  # 🌟 提取书名 ID

    current_volume_num = (current_chapter_num - 1) // 30 + 1
    is_new_volume = (current_chapter_num == 1) or ((current_chapter_num - 1) % 30 == 0)

    if volume_phases and volume_phases.strip() != "" and not is_new_volume:
        return {}

    print(f"📜 [Volume-Planner] 触发第 {current_volume_num} 卷规划！正在将本卷切分为【前、中、后】三期...")

    llm = get_llm(model_type="main", temperature=0.3)
    book_outline = state.get("book_outline_context", "暂无总纲")

    structured_llm = llm.with_structured_output(VolumePhases)
    try:
        phase_result: VolumePhases = await structured_llm.ainvoke([
            SystemMessage(content=LAYER2_VOLUME_PROMPT.format(
                book_outline=book_outline,
                current_volume_num=current_volume_num
            )),
            HumanMessage(content="请生成当前分卷的三期拆解大纲。")
        ])
        phase_json = json.dumps(phase_result.model_dump(), ensure_ascii=False, indent=2)
        if current_chapter_num > 1 and is_new_volume:
            print("🧹 [Volume-Planner] 新卷大纲生成成功！正在安全清理上一卷的 RAG 剧情库，迎接新地图...")
            try:
                RAGEngine(book_id=current_book_id).reset_volume_store()  # 🌟 隔离清理
            except Exception as e:
                print(f"⚠️ RAG 清理异常: {e}")

        return {"current_volume_phases": phase_json}
    except Exception as e:
        print(f"⚠️ [Volume-Planner] 异常: {e}。旧大纲和旧 RAG 数据已保留，防止断档。")
        return {}

# ==========================================
# 🗺️ 节点三：单期统筹编剧 (Phase Planner)
# ==========================================
async def phase_planner_node(state: dict) -> Dict[str, Any]:
    """负责将当前期 (如前期) 切分为 10 章具体梗概"""
    phase_chapters = state.get("current_phase_chapters", "")
    current_chapter_num = state.get("current_chapter_num", 1)
    current_book_id = state.get("book_id", "default_book")  # 🌟 提取书名 ID

    is_new_phase = (current_chapter_num == 1) or ((current_chapter_num - 1) % 10 == 0)

    if phase_chapters and phase_chapters.strip() != "" and not is_new_phase:
        return {}

    phase_names = ["前期", "中期", "后期"]
    current_phase_index = ((current_chapter_num - 1) // 10) % 3
    current_phase_name = phase_names[current_phase_index]

    print(f"📑 [Phase-Planner] 触发跨期推演！当前进入本卷的【{current_phase_name}】，推演十章剧情...")

    llm = get_llm(model_type="main", temperature=0.2)
    world_bible = state.get("world_bible_context", "")
    volume_phases = state.get("current_volume_phases", "")

    try:
        rag_engine = RAGEngine(book_id=current_book_id)  # 🌟 隔离实例
        history_context = rag_engine.retrieve_context(query=volume_phases, k_global=1, k_volume=2, k_phase=1)
    except:
        history_context = "（暂无历史）"

    structured_llm = llm.with_structured_output(PhaseChapters)
    try:
        chapters_result: PhaseChapters = await structured_llm.ainvoke([
            SystemMessage(content=LAYER3_PHASE_PROMPT.format(
                world_bible=world_bible,
                volume_phases=volume_phases,
                history_context=history_context,
                current_phase_name=current_phase_name
            )),
            HumanMessage(content="请推演本期 10 章的具体梗概。")
        ])
        chapters_json = json.dumps(chapters_result.model_dump(), ensure_ascii=False, indent=2)
        if current_chapter_num > 1 and is_new_phase:
            print("🧹 [Phase-Planner] 新期推演成功！正在安全清理上一期的 RAG 细节碎片，防止记忆污染...")
            try:
                RAGEngine(book_id=current_book_id).reset_phase_store()  # 🌟 隔离清理
            except Exception as e:
                pass

        return {"current_phase_chapters": chapters_json}
    except Exception as e:
        print(f"⚠️ [Phase-Planner] 异常: {e}。旧大纲和旧 RAG 细节已保留。")
        return {}


# ==========================================
# 📍 节点四：单章节拍拆解员 (Chapter/Beat Planner)
# ==========================================
async def chapter_planner_node(state: dict) -> Dict[str, Any]:
    """取代原有的 plot_planner_node，专注于生成微观 3-5 个节拍"""
    current_chapter_num = state.get("current_chapter_num", 1)
    current_book_id = state.get("book_id", "default_book")  # 🌟 提取书名 ID
    print(f"📍 [Chapter-Planner] 正在严格对齐本期十章梗概，拆解第 {current_chapter_num} 章节拍器...")

    llm = get_llm(model_type="main", temperature=0.2)
    world_bible = state.get("world_bible_context", "")
    phase_chapters = state.get("current_phase_chapters", "")
    volume_phases = state.get("current_volume_phases", "（暂无分卷大纲）")

    try:
        tracker = KVTracker(book_id=current_book_id)  # 🌟 隔离实例
        current_kv_state = tracker.get_world_bible_snapshot()
        unresolved_threads = tracker.get_active_threads_snapshot()
        current_kv_state += f"\n\n{unresolved_threads}"

        try:
            fast_llm = get_llm(model_type="fast", temperature=0.1)
            rewriter_llm = fast_llm.with_structured_output(RAGQueryPlan)

            rewriter_prompt = (
                f"你是一个RAG检索路由专家。当前准备写第 {current_chapter_num} 章。\n"
                f"【本期大纲参考】:\n{phase_chapters}\n\n"
                f"任务：请分析当前章的剧情重点，提取精准的关键词，并动态分配三层数据库的检索额度 K 值。"
            )

            rag_plan: RAGQueryPlan = await rewriter_llm.ainvoke([HumanMessage(content=rewriter_prompt)])

            print(f"   [🔍 RAG 智能路由] 关键词: {rag_plan.optimized_query} | K值分配: Global={rag_plan.k_global}, Volume={rag_plan.k_volume}, Phase={rag_plan.k_phase}")

            rag_engine = RAGEngine(book_id=current_book_id)  # 🌟 隔离实例
            history_context = rag_engine.retrieve_context(
                query=rag_plan.optimized_query,
                k_global=rag_plan.k_global,
                k_volume=rag_plan.k_volume,
                k_phase=rag_plan.k_phase
            )
        except Exception as e:
            print(f"⚠️ [Query-Rewriter 异常，降级为默认模糊检索]: {e}")
            rag_engine = RAGEngine(book_id=current_book_id)  # 🌟 隔离实例
            history_context = rag_engine.retrieve_context(
                query=phase_chapters, k_global=1, k_volume=2, k_phase=2
            )
    except Exception as e:
        print(f"⚠️ [状态提取异常]: {e}")
        current_kv_state, history_context = "（暂无角色与伏笔状态）", "（暂无历史剧情）"

    cliffhanger_rule = "   - 结尾必须设置【悬念钩子】。" if settings.CLIFFHANGER_REQUIREMENT else ""

    sys_prompt = LAYER4_CHAPTER_PROMPT.format(
        chapter_num=current_chapter_num,
        world_bible=world_bible,
        volume_phases=volume_phases,
        phase_chapters=phase_chapters,
        kv_state=current_kv_state,
        history_context=history_context,
        cliffhanger_rule=cliffhanger_rule
    )

    structured_llm = llm.with_structured_output(ChapterOutline)

    try:
        planner_response: ChapterOutline = await structured_llm.ainvoke([
            SystemMessage(content=sys_prompt),
            HumanMessage(
                content=f"请生成第 {current_chapter_num} 章节拍器。如果剧情合适，请优先从【未解伏笔/悬念/仇恨池】中挑选 1-2 个进行推进或彻底解决（填坑）。")
        ])

        beat_sheet_json = json.dumps(planner_response.model_dump(), ensure_ascii=False, indent=2)

        return {
            "current_beat_sheet": beat_sheet_json,
            "rag_history_context": history_context
        }

    except Exception as e:
        print(f"⚠️ [Chapter-Planner] 异常: {e}")
        return {"current_beat_sheet": "（大纲生成异常，请主笔自由发挥）"}