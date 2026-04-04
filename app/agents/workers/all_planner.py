# app/agents/workers/all_planner.py

import json
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.core.llm_factory import get_llm
from app.core.config import settings
from app.memory.kv_tracker import KVTracker
from app.memory.rag_engine import RAGEngine

# ⚠️ 注意：以下 Schema 需要你在 protocols/a2a_schemas.py 中新增定义
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
你的任务是提取《全书总纲》中【当前卷】的核心目标，将其严格切分为“前、中、后”三期。

【全局世界观与十卷总纲】：
{book_outline}

要求：
- 前期（约10章）：起与承，引入本卷新地图/新矛盾，主角遭遇打压或接到任务。
- 中期（约10章）：转与蓄力，主角寻找破局之法，获得关键道具或实力突破。
- 后期（约10章）：合与高潮，终极对决，打脸反派，收获战利品并引出下一卷钩子。
"""

# 3. 第三层：单期十章 (10章)
LAYER3_PHASE_PROMPT = """你是一个精细的网文【单期统筹编剧】。
你的任务是基于当前卷的【当前期 (前/中/后期)】目标，规划出具体的【十章】剧情梗概。

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
【本期十章梗概】：
{phase_chapters}
【🌟当前人物与物品状态快照 (KV Database)】：
{kv_state}
【🌟相关历史剧情与伏笔参考 (RAG Database)】：
{history_context}

要求：
1. 宏观对齐：本章节拍必须吻合大纲指派的任务。
2. 网文公式约束（强制）：必须包含至少一个【爽点/打脸/装逼】环节。
{cliffhanger_rule}
"""


# ==========================================
# 🗺️ 节点一：全书总架构师 (Book Planner)
# ==========================================
def book_planner_node(state: dict) -> Dict[str, Any]:
    """负责初始化世界观，并生成全书 10 卷大纲"""
    book_outline = state.get("book_outline_context", "")

    if book_outline and book_outline.strip() != "":
        return {}  # 已存在则直接跳过

    print("📚 [Book-Planner] 检测到全新长篇，正在初始化《全书总纲》(10卷) 与世界观...")
    llm = get_llm(model_type="main", temperature=0.3)
    user_input = state.get("messages", [HumanMessage(content="请按网文套路推进")])[-1].content

    # 这里可以使用 structured_output 绑定 BookOutline Schema
    structured_llm = llm.with_structured_output(BookOutline)
    messages = [
        SystemMessage(content=LAYER1_BOOK_PROMPT),
        HumanMessage(content=f"【用户初始脑洞】：{user_input}")
    ]

    try:
        book_result: BookOutline = structured_llm.invoke(messages)
        book_json = json.dumps(book_result.model_dump(), ensure_ascii=False, indent=2)

        # 🌟 知识库防漏水：第一时间将世界观灌入全局 RAG
        try:
            rag_engine = RAGEngine()
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
def volume_planner_node(state: dict) -> Dict[str, Any]:
    """负责将当前卷切分为前、中、后三期"""
    volume_phases = state.get("current_volume_phases", "")

    # 逻辑：如果没有分卷三期大纲，或者当前章数超出了本卷范围，则触发生成
    if volume_phases and volume_phases.strip() != "":
        return {}

    print("📜 [Volume-Planner] 正在将当前卷切分为【前、中、后】三期...")
    llm = get_llm(model_type="main", temperature=0.3)
    book_outline = state.get("book_outline_context", "暂无总纲")

    structured_llm = llm.with_structured_output(VolumePhases)
    try:
        phase_result: VolumePhases = structured_llm.invoke([
            SystemMessage(content=LAYER2_VOLUME_PROMPT.format(book_outline=book_outline)),
            HumanMessage(content="请生成当前分卷的三期拆解大纲。")
        ])
        phase_json = json.dumps(phase_result.model_dump(), ensure_ascii=False, indent=2)
        return {"current_volume_phases": phase_json}
    except Exception as e:
        print(f"⚠️ [Volume-Planner] 异常: {e}")
        return {}


# ==========================================
# 🗺️ 节点三：单期统筹编剧 (Phase Planner)
# ==========================================
def phase_planner_node(state: dict) -> Dict[str, Any]:
    """负责将当前期 (如前期) 切分为 10 章具体梗概"""
    phase_chapters = state.get("current_phase_chapters", "")

    if phase_chapters and phase_chapters.strip() != "":
        return {}

    print("📑 [Phase-Planner] 正在基于本期任务，详细推演【十章】连贯剧情...")
    llm = get_llm(model_type="main", temperature=0.2)

    world_bible = state.get("world_bible_context", "")
    volume_phases = state.get("current_volume_phases", "")

    try:
        rag_engine = RAGEngine()
        history_context = rag_engine.retrieve_context(query=volume_phases, k=4)
    except:
        history_context = "（暂无历史）"

    structured_llm = llm.with_structured_output(PhaseChapters)
    try:
        chapters_result: PhaseChapters = structured_llm.invoke([
            SystemMessage(content=LAYER3_PHASE_PROMPT.format(
                world_bible=world_bible,
                volume_phases=volume_phases,
                history_context=history_context
            )),
            HumanMessage(content="请推演本期 10 章的具体梗概。")
        ])
        chapters_json = json.dumps(chapters_result.model_dump(), ensure_ascii=False, indent=2)
        return {"current_phase_chapters": chapters_json}
    except Exception as e:
        print(f"⚠️ [Phase-Planner] 异常: {e}")
        return {}


# ==========================================
# 📍 节点四：单章节拍拆解员 (Chapter/Beat Planner)
# ==========================================
def chapter_planner_node(state: dict) -> Dict[str, Any]:
    """取代原有的 plot_planner_node，专注于生成微观 3-5 个节拍"""
    current_chapter_num = state.get("current_chapter_num", 1)
    print(f"📍 [Chapter-Planner] 正在严格对齐本期十章梗概，拆解第 {current_chapter_num} 章节拍器...")

    llm = get_llm(model_type="main", temperature=0.2)
    world_bible = state.get("world_bible_context", "")
    phase_chapters = state.get("current_phase_chapters", "")

    # 🌟 核心升级：提取冷热隔离的 KV、伏笔悬念池 以及 三层立体 RAG
    try:
        tracker = KVTracker()
        # 1. 获取过滤后的活跃角色状态
        current_kv_state = tracker.get_world_bible_snapshot()

        # 2. 获取未解伏笔池，拼接到状态中给大模型看
        unresolved_threads = tracker.get_active_threads_snapshot()
        current_kv_state += f"\n\n{unresolved_threads}"

        # 3. 适配三层架构 RAG，从全局、分卷、单期分别抽调记忆
        rag_engine = RAGEngine()
        history_context = rag_engine.retrieve_context(
            query=phase_chapters,
            k_global=1,  # 捞 1 条世界观或死仇
            k_volume=2,  # 捞 2 条本卷主线
            k_phase=2  # 捞 2 条上一章的微观细节
        )
    except Exception as e:
        print(f"⚠️ [状态提取异常]: {e}")
        current_kv_state, history_context = "（暂无角色与伏笔状态）", "（暂无历史剧情）"

    cliffhanger_rule = "   - 结尾必须设置【悬念钩子】。" if settings.CLIFFHANGER_REQUIREMENT else ""

    # 组装系统 Prompt
    sys_prompt = LAYER4_CHAPTER_PROMPT.format(
        chapter_num=current_chapter_num,
        world_bible=world_bible,
        phase_chapters=phase_chapters,
        kv_state=current_kv_state,
        history_context=history_context,
        cliffhanger_rule=cliffhanger_rule
    )

    structured_llm = llm.with_structured_output(ChapterOutline)

    try:
        planner_response: ChapterOutline = structured_llm.invoke([
            SystemMessage(content=sys_prompt),
            # 🌟 核心升级：在最后一句用户指令中，强烈暗示 AI 推进或解决伏笔
            HumanMessage(
                content=f"请生成第 {current_chapter_num} 章节拍器。如果剧情合适，请优先从【未解伏笔/悬念/仇恨池】中挑选 1-2 个进行推进或彻底解决（填坑）。")
        ])

        beat_sheet_json = json.dumps(planner_response.model_dump(), ensure_ascii=False, indent=2)

        # 将生成的单章大纲和历史参考一起向下游(主笔节点)传递
        return {
            "current_beat_sheet": beat_sheet_json,
            "rag_history_context": history_context
        }

    except Exception as e:
        print(f"⚠️ [Chapter-Planner] 异常: {e}")
        return {"current_beat_sheet": "（大纲生成异常，请主笔自由发挥）"}