# app/agents/workers/all_planner.py

import json
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.core.llm_factory import get_llm
from app.core.config import settings
from app.memory.kv_tracker import KVTracker
from app.memory.rag_engine import RAGEngine
from protocols.a2a_schemas import ChapterOutline, VolumeOutline

# ==========================================
# 🧠 提示词定义区
# ==========================================

WORLD_BUILDER_PROMPT = """你是一个顶级的下沉市场网文【世界观架构师】。
用户的输入可能只是一个模糊的灵感或几句话的脑洞。
你的任务是将它扩充为一份结构化的《世界观圣经》（World Bible）。

请包含以下内容：
1. 核心设定（世界背景、力量体系或金手指机制）
2. 主角人设（性格、核心动机、初始金手指）
3. 全书宏观主线（主角最终要达成的目标或对抗的终极反派）

请直接输出纯文本形式的世界观设定，无需 JSON 格式。结构清晰，设定必须极具“网文爽感”。
"""

MACRO_PLANNER_PROMPT = """你是一个顶尖的网文【总架构师】。
你的任务是基于《世界观圣经》，为小说规划一段严密的【分卷大纲】（推演接下来的 10-20 章核心剧情线）。

【世界观圣经】：
{world_bible}

请确保主线清晰、爽点密集，主角要有明确的中短期目标（如：夺得门派大比第一、攒够钱买极品法宝等）。
"""

MICRO_PLANNER_PROMPT = """你是一个经验丰富、极其严苛的番茄【执行主编 / 节拍拆解员】。
你要采用“层次化拆解（Hierarchical Generation）”的策略，基于《宏观分卷大纲》中对第 {chapter_num} 章的规划，为本章拆解出详细的“单章节拍器（Beat Sheet）”。

【当前世界观圣经】：
{world_bible}

【🗺️ 全局宏观分卷大纲】：
{macro_story_tree}

【🌟当前人物与物品状态快照 (KV Database)】：
{kv_state}

【🌟相关历史剧情与伏笔参考 (RAG Database)】：
{history_context}

【层次化拆解要求】：
1. 宏观对齐：仔细阅读《分卷大纲》，本章的剧情必须完美吻合大纲对第 {chapter_num} 章的任务指派。
2. 微观节拍：将本章拆解为 3-5 个具体的剧情节拍（Beat）。
3. 网文公式约束（强制）：必须包含至少一个【爽点/打脸/装逼】环节。
{cliffhanger_rule}
"""


# ==========================================
# 🗺️ 节点一：宏观分卷规划师 (Macro-Planner)
# ==========================================
def macro_planner_node(state: dict) -> Dict[str, Any]:
    """
    负责初始化世界观，并生成宏观级别的分卷大纲（10-20章）。
    只有当世界观为空，或当前卷大纲为空时才会真正触发重规划。
    """
    messages = state.get("messages", [])
    world_bible = state.get("world_bible_context", "")
    macro_tree = state.get("macro_story_tree", "")

    user_input = "请按照网文套路正常推进。"
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            user_input = m.content
            break

    llm = get_llm(model_type="main", temperature=0.3)
    updates = {}

    # --- 阶段一：World-Builder 职责 ---
    if not world_bible or world_bible.strip() == "":
        print("🌍 [Macro-Planner] 正在初始化《世界观圣经》...")
        wb_messages = [
            SystemMessage(content=WORLD_BUILDER_PROMPT),
            HumanMessage(content=f"【用户初始脑洞】：{user_input}")
        ]
        world_bible = llm.invoke(wb_messages).content.strip()
        updates["world_bible_context"] = world_bible

    # --- 阶段二：Macro-Story 职责 ---
    # 如果当前没有分卷大纲，或者达到了触发条件，则生成分卷大纲
    if not macro_tree or macro_tree.strip() == "":
        print("🗺️ [Macro-Planner] 正在进行宏观剧情推演，生成《分卷大纲》...")

        structured_llm = llm.with_structured_output(VolumeOutline)
        planner_messages = [
            SystemMessage(content=MACRO_PLANNER_PROMPT.format(world_bible=world_bible)),
            HumanMessage(content=f"【用户最新指令】：{user_input}\n请规划本卷大纲。")
        ]

        try:
            volume_outline: VolumeOutline = structured_llm.invoke(planner_messages)
            macro_tree_json = json.dumps(volume_outline.model_dump(), ensure_ascii=False, indent=2)
            updates["macro_story_tree"] = macro_tree_json
            print("✅ [Macro-Planner] 《分卷大纲》已锚定。")
        except Exception as e:
            print(f"⚠️ [Macro-Planner] 分卷大纲生成异常: {e}")
            updates["macro_story_tree"] = "（宏观大纲暂缺，请主笔自行推进）"

    return updates


# ==========================================
# 📍 节点二：微观节拍拆解员 (Micro-Planner)
# ==========================================
def plot_planner_node(state: dict) -> Dict[str, Any]:
    """
    职责：接收宏观大纲，生成单章节拍器
    """
    messages = state.get("messages", [])
    world_bible = state.get("world_bible_context", "")
    macro_tree = state.get("macro_story_tree", "（暂无宏观大纲）")
    current_chapter_num = state.get("current_chapter_num", 1)

    user_input = "请继续。"
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            user_input = m.content
            break

    print(f"📍 [Micro-Planner] 正在严格对齐宏观大纲，拆解第 {current_chapter_num} 章节拍器...")
    llm = get_llm(model_type="main", temperature=0.2)
    updates = {}

    try:
        kv_tracker = KVTracker()
        current_kv_state = kv_tracker.get_world_bible_snapshot()
    except Exception as e:
        current_kv_state = "（暂无角色状态）"

    try:
        rag_engine = RAGEngine()
        history_context = rag_engine.retrieve_context(query=user_input, k=3)
    except Exception as e:
        history_context = "（暂无历史剧情）"

    cliffhanger_rule = "   - 章节结尾必须设置一个【悬念钩子（Cliffhanger）】，吸引读者看下一章。" if settings.CLIFFHANGER_REQUIREMENT else ""

    planner_sys_prompt = MICRO_PLANNER_PROMPT.format(
        chapter_num=current_chapter_num,
        world_bible=world_bible,
        macro_story_tree=macro_tree,
        kv_state=current_kv_state,
        history_context=history_context,
        cliffhanger_rule=cliffhanger_rule
    )

    structured_llm = llm.with_structured_output(ChapterOutline)
    try:
        planner_response: ChapterOutline = structured_llm.invoke([
            SystemMessage(content=planner_sys_prompt),
            HumanMessage(content=f"【用户补充指令/反馈】：{user_input}\n请开始拆解本章。")
        ])
        beat_sheet_json = json.dumps(planner_response.model_dump(), ensure_ascii=False, indent=2)
        updates["current_beat_sheet"] = beat_sheet_json
    except Exception as e:
        print(f"⚠️ [Micro-Planner] 拆解异常: {e}")
        fallback_sheet = {
            "chapter_title": f"第 {current_chapter_num} 章",
            "beats": [{"plot_summary": "大纲生成异常，请主笔自由发挥。", "is_climax": False, "hook": ""}],
            "mandatory_elements": []
        }
        beat_sheet_json = json.dumps(fallback_sheet, ensure_ascii=False)
        updates["current_beat_sheet"] = beat_sheet_json

    # 再次基于生成的节拍反向查 RAG 补充历史
    try:
        rag_engine = RAGEngine()
        history_context = rag_engine.retrieve_context(query=beat_sheet_json, k=3)
    except:
        pass
    updates["rag_history_context"] = history_context

    if state.get("current_chapter_num") is None:
        updates["current_chapter_num"] = current_chapter_num

    updates["messages"] = [
        AIMessage(content=f"[Plot-Planner] 已完成第 {current_chapter_num} 章的大纲拆解。", name="Plot_Planner")]

    return updates