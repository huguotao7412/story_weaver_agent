# app/agents/workers/plot_planner.py

import json
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage

# 引入你的 LLM 工厂与配置项
from app.core.llm_factory import get_llm
from app.core.config import settings
from app.memory.kv_tracker import KVTracker
from app.memory.rag_engine import RAGEngine

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

PLOT_PLANNER_PROMPT = """你是一个经验丰富、极其严苛的番茄【网文主编】。
你要采用“层次化拆解（Hierarchical Generation）”的策略，基于《世界观圣经》及当前的动态状态，为小说的第 {chapter_num} 章规划详细的“单章节拍器（Beat Sheet）”。

【当前世界观圣经】：
{world_bible}

【🌟当前人物与物品状态快照 (KV Database)】：
{kv_state}

【🌟相关历史剧情与伏笔参考 (RAG Database)】：
{history_context}

【层次化规划要求】：
1. 宏观对齐：本章剧情必须服务于全书主线，并合理延续当前的“人物状态”与“历史伏笔”。
2. 微观节拍：将本章拆解为 3-5 个具体的剧情节拍（Beat）。
3. 网文公式约束（强制）：
   - 必须包含至少一个【爽点/打脸/装逼】环节。
{cliffhanger_rule}

请严格以 JSON 格式输出，数据结构必须如下：
{{
    "book_macro_direction": "简述全书宏观走向",
    "current_volume_goal": "简述当前阶段/本卷的核心目标",
    "chapter_title": "本章标题",
    "mandatory_elements": ["本章必须出现的关键人物", "必须提及的重要道具/设定"],
    "beats": [
        {{
            "plot_summary": "本段节拍的情节摘要（如：主角进入拍卖会，遭到反派嘲讽）",
            "is_climax": false,
            "hook": ""
        }},
        {{
            "plot_summary": "情节摘要（如：主角展露金手指，震惊全场，打脸反派）",
            "is_climax": true,
            "hook": ""
        }},
        {{
            "plot_summary": "情节摘要",
            "is_climax": false,
            "hook": "如果启用了悬念钩子，请在这里填写具体的悬念设计"
        }}
    ]
}}

注意：只返回合法的 JSON 字符串，不要包含 ```json 等 Markdown 标签。
"""


# ==========================================
# 🚀 核心节点逻辑
# ==========================================

def plot_planner_node(state: dict) -> Dict[str, Any]:
    """
    🗺️ World-Builder & Plot-Planner 复合节点
    职责：初始化世界观（如果为空） -> 层次化拆解本章大纲 -> 生成节拍器
    """
    messages = state.get("messages", [])
    world_bible = state.get("world_bible_context", "")
    current_chapter_num = state.get("current_chapter_num", 1)

    user_input = "请继续按照大纲推进剧情。"
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            user_input = m.content
            break

    llm = get_llm(model_type="main", temperature=0.2)
    updates = {}

    # --- 阶段一：World-Builder 职责 ---
    if not world_bible or world_bible.strip() == "":
        print("🌍 [Plot-Planner] 正在初始化《世界观圣经》...")
        wb_messages = [
            SystemMessage(content=WORLD_BUILDER_PROMPT),
            HumanMessage(content=f"【用户初始脑洞】：{user_input}")
        ]
        wb_response = llm.invoke(wb_messages)
        world_bible = wb_response.content.strip()
        updates["world_bible_context"] = world_bible

    # --- 阶段二：Plot-Planner 职责 ---
    print(f"🗺️ [Plot-Planner] 正在进行层次化拆解，生成第 {current_chapter_num} 章节拍器...")

    try:
        kv_tracker = KVTracker()
        current_kv_state = kv_tracker.get_world_bible_snapshot()
    except Exception as e:
        print(f"⚠️ [Plot-Planner] KVTracker 读取失败，使用空状态: {e}")
        current_kv_state = "（当前暂无角色状态快照）"

    try:
        rag_engine = RAGEngine()
        # 这里用 user_input 作为 query 进行检索
        history_context = rag_engine.retrieve_context(query=user_input, k=3)
    except Exception as e:
        print(f"⚠️ [Plot-Planner] RAGEngine 读取失败，使用空状态: {e}")
        history_context = "（当前暂无历史剧情可供参考）"

    cliffhanger_rule = "   - 章节结尾必须设置一个【悬念钩子（Cliffhanger）】，吸引读者看下一章。" if settings.CLIFFHANGER_REQUIREMENT else ""

    planner_sys_prompt = PLOT_PLANNER_PROMPT.format(
        chapter_num=current_chapter_num,
        world_bible=world_bible,
        kv_state=current_kv_state,  # 注入动态人物状态
        history_context=history_context,  # 注入 RAG 历史伏笔
        cliffhanger_rule=cliffhanger_rule
    )

    planner_messages = [
        SystemMessage(content=planner_sys_prompt),
        HumanMessage(content=f"【用户补充指令/反馈】：{user_input}\n请开始拆解并输出 JSON。")
    ]

    planner_response = llm.invoke(planner_messages)
    content = planner_response.content.strip()

    if content.startswith("```json"):
        content = content[7:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    try:
        beat_sheet_dict = json.loads(content)
        beat_sheet_json = json.dumps(beat_sheet_dict, ensure_ascii=False, indent=2)
        updates["current_beat_sheet"] = beat_sheet_json
    except json.JSONDecodeError:
        print("⚠️ [Plot-Planner] JSON 解析失败，触发 Fallback 机制。")
        fallback_sheet = {
            "chapter_title": f"第 {current_chapter_num} 章",
            "beats": [{"plot_summary": content, "is_climax": False, "hook": ""}]
        }
        beat_sheet_json = json.dumps(fallback_sheet, ensure_ascii=False)
        updates["current_beat_sheet"] = beat_sheet_json

    print("🔍 [Plot-Planner] 正在基于本章节拍器，向 RAG 引擎反向检索历史伏笔...")
    try:
        rag_engine = RAGEngine()
        # 用刚刚结构化出来的、几百字的高密度大纲作为 Query 去捞取历史剧情
        history_context = rag_engine.retrieve_context(query=beat_sheet_json, k=3)
    except Exception as e:
        print(f"⚠️ [Plot-Planner] RAGEngine 读取失败: {e}")
        history_context = "（当前暂无历史剧情可供参考）"

    # 将检索到的伏笔存入图状态中
    updates["rag_history_context"] = history_context

    if state.get("current_chapter_num") is None:
        updates["current_chapter_num"] = current_chapter_num

    return updates