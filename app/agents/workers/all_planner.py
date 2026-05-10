# app/agents/workers/all_planner.py

import json
import re
import asyncio
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.core.llm_factory import get_llm
from app.memory.kv_tracker import AsyncKVTracker
from app.memory.rag_engine import RAGEngine

from protocols.a2a_schemas import BookOutline, VolumePhases, PhaseChapters, ChapterOutline

# ==========================================
# 🧠 四层提示词定义区
# ==========================================

# 1. 第一层：全书总纲 (10卷)
LAYER1_BOOK_PROMPT = """你是一个白金级网文【全书总架构师】。
你的任务是基于用户的初始脑洞，构建《世界观圣经》并规划【全书十卷】的总脉络（预计百万字规模）。
【注意】：你必须将风土人情（world_lore）和严格的境界战力等级（power_system_rules）分开输出。

【核心规划任务】：
1. 《世界观圣经》：核心设定、力量体系、主角初始人设与终极目标。
2. 《全书十卷大纲》：规划 10 个分卷的名字和核心任务（主角从弱小到巅峰的成长轨迹）。

🚨 【输出方式】：
请直接输出一个完整的 JSON 对象，不要包裹在 markdown 代码块中，不要添加任何解释性文本。
"""

# 2. 第二层：分卷五期大纲 (🌟 融入软修正机制)
LAYER2_VOLUME_PROMPT = """你是一个资深网文【分卷大纲主编】。
你的任务是提取《全书总纲》中【第 {current_volume_num} 卷】的核心目标，将其严格切分为【5期】（每期约10章，本卷共50章）。

【初始全局世界观与十卷总纲】：
{book_outline}

【🚨 当前真实世界快照 (最新状态与装备)】：
{kv_snapshot}

【📜 宏观前情回顾 (前几卷的真实剧情史诗回顾)】：
{previous_volume_summaries}

【🔥 最高权限红线：软修正与动态推演】：
你现在拥有《初始大纲》和《当前真实世界快照》及《前情回顾》。主角的实际发展可能已偏离最初的设定（例如原定反派提前死亡、获得了意料之外的法宝或新境界）。
在规划新一卷时，**必须以【真实的快照和前情回顾】为绝对基准！**如果初始总纲的规划与现实冲突，请自动抛弃旧大纲的设定，顺着当前的真实脉络，为主线重新制定合理的下一卷剧情走向！

要求：必须采用“腰部小高潮+尾部大高潮”的经典五幕剧结构！
- 第1期（潜龙在渊）：初入新地图，试探、情报收集、稳扎稳打。
- 第2期（风云渐起）：卷入纷争，展露头角，获得第一波神装或小机缘。
- 第3期（腰部高潮）：第一个大高潮爆发！击杀明面Boss，发现深层阴谋。
- 第4期（极限蓄力）：压抑、紧迫的疯狂寻找机缘与突破大境界。
- 第5期（终局超脱）：斩杀终极Boss，势力洗牌，并在本期进行卷末结算与告别。

🚨 【输出方式】：
请直接输出一个完整的 JSON 对象，不要包裹在 markdown 代码块中，不要添加任何解释性文本。
"""

# 3. 第三层：单期十章 (10章) (🌟 融入软修正机制)
LAYER3_PHASE_PROMPT = """你是一个精细的网文【单期统筹编剧】。
你的任务是基于当前卷的【{current_phase_name}】目标，规划出具体的【十章】剧情梗概。

【本卷宏观规划与历史参考】：
{volume_phases}
{history_context}

【🚨 当前真实世界快照 (最新状态与装备)】：
{kv_snapshot}

【📜 前情回顾 (本卷前几期的真实剧情总结)】：
{previous_phase_summaries}

【🔥 最高权限红线：软修正与动态推演】：
你现在拥有《本卷宏观规划》和《当前真实世界快照》及《前情回顾》。在拆解本期大纲时，**必须以【真实的快照和前情回顾】为绝对基准！**如果上层宏观规划与当前的现实冲突（例如某配角已死），请自动抛弃旧规划设定，顺着当前的真实脉络微调本期的走向！

【🌟核心心流公式（必须遵守）】：
这10章的节奏必须遵循“3低-3中-3高-1低”的波浪线，并为每章打上 tension_level 标签：
- 第1-3章 (Low)：舒缓、铺垫、情报收集、日常。
- 第4-6章 (Medium)：小冲突、拉扯、试探、悬疑探索。
- 第7-9章 (High)：本期核心矛盾爆发、生死战。
- 第10章 (Low)：本期小结算、战利品清点、期待感建立（绝对禁止在第10章引出新生死危机）。

🚨 【输出方式】：
请直接输出一个完整的 JSON 对象，不要包裹在 markdown 代码块中，不要添加任何解释性文本。
"""

# 4. 第四层：单章节拍
LAYER4_CHAPTER_PROMPT = """你是一个极其严苛的番茄【执行主编 / 节拍拆解员】。
基于《十章剧情梗概》中对第 {chapter_num} 章的规划，为本章拆解出详细的 4-6 个“单章节拍器（Beat Sheet）”。

{human_override_instruction}

【🎬 物理级无缝接续锚点 (绝对红线)】：
{previous_chapter_ending}

【📚 连载剧情脉络 (前两章摘要参考)】：
{recent_chapters_summary}

【本期梗概 (已开启防剧透遮罩)】：
{focused_phase_chapters}

【⚖️ 战力铁律 (绝对不可违背)】：
{power_system_rules}
【当前世界观与设定】：
{world_bible}
【👑本卷核心大目标 (防偏题必备)】：
{volume_phases}
【🌟当前人物与物品状态快照 (KV Database)】：
{kv_state}
【🌟相关历史剧情与伏笔参考 (RAG Database)】：
{history_context}

【🛑 严禁抢跑与无缝衔接铁律（必须遵守）】：
1. 你的第1个节拍 (Beat 1) 必须【严丝合缝】地接上上方《上一章最后500字原文》的最后一个动作或最后一句话！绝对禁止出现任何时间跳跃！
2. 你的最后1个节拍 (最后一个节拍) 必须【严格止步】于上方【本期梗概】中属于本章的核心任务完成的瞬间。
3. 绝对禁止为了凑节拍数而把进度推到本章目标之外，如果你在节拍里写了属于【下一章预告】的内容，内审将直接判定 FAIL！
4. 🚫【防重影铁律】：仔细阅读上方的《最近两章完整原文》，你的节拍必须是在前文基础上的“向前推进”！绝对禁止在你的节拍中安排与前两章高度重复的对话、心理活动或冲突桥段！

【🎬 分镜头与权重分配法则 (极大提升画面分辨率)】：
1. 必须顺应当前的情绪节奏（tension_level）：这 6-8 个微观节拍必须严格服从上方的心流节奏。
2. 必须为每个节拍分配合理的 `word_count_weight` (如 10%, 40%)，总和应约为 100%。
3. 动态节奏要求：
{climax_rule}
4. 动态钩子要求：
{cliffhanger_rule}

🚨 【格式强约束】：
必须且只能以纯 JSON 格式输出。
1. beats 数组中存放节拍。
2. mandatory_elements 数组中，请务必提取出本章真正出现的 4-6 个核心要素（如出场人物名、关键道具名），用于后续的记忆对齐。
"""


class RAGQueryPlan(BaseModel):
    """动态决定三层 RAG 检索策略"""
    optimized_query: str = Field(
        description="从当前章梗概中提取的核心关键词（如特定人名、地名、功法），用空格分隔，滤除无用废话")
    k_global: int = Field(description="全局设定库检索量(0-3)。若涉及世界观揭秘、大境界突破、远古大伏笔，请给2-3；纯日常给0。")
    k_volume: int = Field(description="分卷主线库检索量(0-3)。若涉及本卷核心反派冲突、长线任务推进，请给2-3；否则给1。")
    k_phase: int = Field(
        description="近期细节库检索量(1-4)。若正在进行连贯的战斗、动作接续、紧凑对话，请给3-4；新开地图或时间跳跃给1。")


# ==========================================
# 🛠️ JSON 提取与安全调用工具函数
# ==========================================
def _extract_json(text: str) -> str:
    """从 LLM 回复中提取 JSON 字符串，支持 markdown 代码块和裸 JSON"""
    # 优先匹配 markdown 代码块
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # 尝试匹配最外层 JSON object
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        return m.group(0).strip()
    return text.strip()


async def _safe_json_invoke(llm, prompt_messages: list, model_cls: Type[BaseModel],
                            node_name: str, max_retries: int = 3, timeout: int = 180) -> BaseModel:
    """安全调用 LLM，要求输出 JSON 并解析为指定 Pydantic 模型。"""

    # 【修复核心 1】：提取 Pydantic 模型的 JSON Schema，准备喂给大模型
    schema_str = json.dumps(model_cls.model_json_schema(), ensure_ascii=False, indent=2)
    schema_instruction = (
        f"\n\n🚨 【强约束格式要求】：\n"
        f"你必须且只能输出一个符合以下 JSON Schema 的 JSON 对象。\n"
        f"绝对不要遗漏任何必填字段，字段类型必须严格一致：\n"
        f"{schema_str}"
    )

    # 【修复核心 2】：将要求拼接到最后一条消息中
    messages_to_send = list(prompt_messages)
    last_msg = messages_to_send[-1]
    if hasattr(last_msg, 'content'):
        messages_to_send[-1] = type(last_msg)(content=last_msg.content + schema_instruction)

    for attempt in range(max_retries):
        try:
            print(f"⏳ [{node_name}] 正在调用大模型 (第 {attempt + 1}/{max_retries} 次)...")
            # 注意这里传入的是修改后的 messages_to_send
            response = await asyncio.wait_for(llm.ainvoke(messages_to_send), timeout=timeout)

            print(f"✅ [{node_name}] 已收到回复，正在解析 JSON...")
            json_str = _extract_json(response.content)
            result = model_cls.model_validate_json(json_str)
            print(f"✅ [{node_name}] JSON 解析成功！")
            return result
        except asyncio.TimeoutError:
            print(f"⏰ [{node_name}] 第 {attempt + 1} 次调用超时 ({timeout}秒)")
            if attempt < max_retries - 1:
                messages_to_send.append(HumanMessage(content="上次调用超时，请直接输出 JSON，不要任何额外文本。"))
        except Exception as e:
            print(f"⚠️ [{node_name}] 第 {attempt + 1} 次调用/解析失败: {e}")
            if attempt < max_retries - 1:
                messages_to_send.append(AIMessage(content=f"你的输出格式有误: {str(e)}"))
                messages_to_send.append(HumanMessage(
                    content=f"请严格按照我上面提供的 JSON Schema 重新输出完整的 JSON。不要自己发明字段名！报错信息：{str(e)}"))
    raise ValueError(f"[{node_name}] 在 {max_retries} 次重试后仍然失败")


# ==========================================
# ✂️ 动态大纲折叠/切片辅助函数
# ==========================================
def get_focused_volume_phases(volume_phases_json: str, current_chapter_num: int) -> str:
    """
    视野聚焦引擎：将十期大纲折叠，只暴露【当前期】、【下一期(过渡)】和【最终期(终局目标)】。
    防止大模型因信息过载而乱带节奏或提前剧透。
    """
    if not volume_phases_json or volume_phases_json == "（暂无分卷大纲）":
        return volume_phases_json

    try:
        data = json.loads(volume_phases_json)
        phases = data.get("phases", [])

        if not phases or len(phases) <= 3:
            return volume_phases_json

        current_phase_idx = ((current_chapter_num - 1) % 50) // 10
        last_phase_idx = len(phases) - 1

        focused_phases = []
        for i, phase in enumerate(phases):
            if i == current_phase_idx or i == current_phase_idx + 1 or i == last_phase_idx:
                focused_phases.append(phase)
            elif i == current_phase_idx + 2 and i < last_phase_idx:
                focused_phases.append({
                    "phase_name": "中间期 (已折叠)",
                    "plot_mission": "【系统已折叠无关的未来剧情，避免剧透，请主笔绝对专注眼前的任务！】"
                })

        data["phases"] = focused_phases
        return json.dumps(data, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"⚠️ [Volume-Filter] 折叠大纲失败: {e}")
        return volume_phases_json


# ==========================================
# ✂️ 新增：单期大纲视野遮罩 (防抢跑核心逻辑)
# ==========================================
def get_focused_phase_chapters(phase_chapters_json: str, current_chapter_num: int) -> str:
    """
    单期大纲视野遮罩：只向大模型暴露【上一章(接续)】【本章(核心)】【下一章(悬念目标)】。
    彻底抹除未来剧情，防止底层节拍器抢跑。
    """
    if not phase_chapters_json or phase_chapters_json == "（暂无期大纲）":
        return phase_chapters_json

    try:
        data = json.loads(phase_chapters_json)
        summaries = data.get("chapter_summaries", [])

        if not summaries:
            return phase_chapters_json

        # 计算在当前10章列表中的索引 (0-9)
        current_idx = (current_chapter_num - 1) % 10

        focused_summaries = []
        for i, chapter in enumerate(summaries):
            if current_idx > 0 and i == current_idx - 1:
                chapter["_system_note"] = "【上一章已发生剧情】请确保本章的第一个节拍与此无缝接续。"
                focused_summaries.append(chapter)
            elif i == current_idx:
                chapter["_system_note"] = "🔥🔥🔥【本章核心任务】你的所有节拍必须且只能推进到这里！绝不允许越界！"
                focused_summaries.append(chapter)
            elif i == current_idx + 1:
                chapter["_system_note"] = "🛑【下一章预告】仅供结尾悬念铺垫参考。绝对禁止在本章的节拍中提前写出这里的剧情！"
                focused_summaries.append(chapter)
            else:
                # 折叠其他无关章节，彻底断绝大模型偷看未来的可能
                focused_summaries.append({
                    "chapter_number": chapter.get("chapter_number"),
                    "core_conflict": "【已隐藏的未来或过去剧情，绝对禁止触碰】"
                })

        data["chapter_summaries"] = focused_summaries
        return json.dumps(data, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"⚠️ [Phase-Filter] 大纲切片失败: {e}")
        return phase_chapters_json


# ==========================================
# 🗺️ 节点一：全书总架构师 (Book Planner)
# ==========================================
async def book_planner_node(state: dict) -> Dict[str, Any]:
    """负责初始化世界观，并生成全书 10 卷大纲"""
    book_outline = state.get("book_outline_context", "")
    current_book_id = state.get("book_id", "default_book")

    if book_outline and book_outline.strip() != "":
        return {"is_book_initialized": True}

    print(f"📚 [Book-Planner] 检测到全新长篇 (Book ID: {current_book_id})，正在初始化《全书总纲》与世界观...")
    llm = get_llm(temperature=0.3)

    user_input = state.get("user_input", "请按网文套路推进")
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

    try:
        book_result: BookOutline = await _safe_json_invoke(
            llm, [
                SystemMessage(content=LAYER1_BOOK_PROMPT),
                HumanMessage(content=prompt_content)
            ],
            BookOutline, "Book-Planner"
        )
        book_json = json.dumps(book_result.model_dump(), ensure_ascii=False, indent=2)

        tracker = AsyncKVTracker(book_id=current_book_id)
        await tracker.init_db()
        await tracker.set_power_system_rules(book_result.power_system_rules)

        try:
            rag_engine = RAGEngine(book_id=current_book_id)
            await asyncio.to_thread(rag_engine.insert_world_bible,
                                    [{"title": "全书世界观与总纲", "content": book_json}])
            print("✅ [Book-Planner] 《全书总纲》已成功灌入全局 RAG 向量空间。")
        except Exception as e:
            print(f"⚠️ [Book-Planner] RAG 持久化异常: {e}")

        return {"book_outline_context": book_json, "world_bible_context": book_result.world_lore,
                "is_book_initialized": True}
    except Exception as e:
        print(f"❌ [Book-Planner] 总纲初始化失败: {e}")
        return {"is_book_initialized": False}


# ==========================================
# 🗺️ 节点二：分卷三期规划师 (Volume Planner)
# ==========================================
async def volume_planner_node(state: dict) -> Dict[str, Any]:
    """负责将当前卷切分为前、中、后三期 (🌟 支持动态软修正)"""
    volume_phases = state.get("current_volume_phases", "")
    current_chapter_num = state.get("current_chapter_num", 1)
    current_book_id = state.get("book_id", "default_book")

    current_volume_num = (current_chapter_num - 1) // 50 + 1
    is_new_volume = (current_chapter_num == 1) or ((current_chapter_num - 1) % 50 == 0)

    if volume_phases and volume_phases.strip() != "" and not is_new_volume:
        return {"is_volume_initialized": True}

    print(f"📜 [Volume-Planner] 触发第 {current_volume_num} 卷规划！正在提取底层状态进行软修正...")

    llm = get_llm(temperature=0.3)
    book_outline = state.get("book_outline_context", "暂无总纲")

    # 🌟 获取最新快照与宏观前情回顾
    tracker = AsyncKVTracker(book_id=current_book_id)
    await tracker.init_db()
    kv_snapshot = await tracker.get_world_bible_snapshot()

    prev_volumes_text = "（这是本书第一卷，暂无前卷剧情）"
    if current_volume_num > 1:
        summaries = await tracker.get_volume_summaries(1, current_volume_num - 1)
        if summaries:
            prev_volumes_text = "\n\n".join(summaries)

    try:
        phase_result: VolumePhases = await _safe_json_invoke(
            llm, [
                SystemMessage(content=LAYER2_VOLUME_PROMPT.format(
                    book_outline=book_outline,
                    current_volume_num=current_volume_num,
                    kv_snapshot=kv_snapshot,
                    previous_volume_summaries=prev_volumes_text
                )),
                HumanMessage(content="请根据当前的真实世界快照和前卷史诗回顾，修正并推演当前分卷的五期拆解大纲。")
            ],
            VolumePhases, "Volume-Planner"
        )
        phase_json = json.dumps(phase_result.model_dump(), ensure_ascii=False, indent=2)

        if current_chapter_num > 1 and is_new_volume:
            print("🧹 [Volume-Planner] 动态新卷大纲生成成功！正在安全清理上一卷的局部 RAG 细节...")
            try:
                await asyncio.to_thread(RAGEngine(book_id=current_book_id).reset_volume_store)
            except Exception as e:
                print(f"⚠️ RAG 清理异常: {e}")

        return {"current_volume_phases": phase_json, "is_volume_initialized": True}
    except Exception as e:
        print(f"❌ [Volume-Planner] 分卷大纲生成失败: {e}")
        return {"is_volume_initialized": False}


# ==========================================
# 🗺️ 节点三：单期统筹编剧 (Phase Planner)
# ==========================================
async def phase_planner_node(state: dict) -> Dict[str, Any]:
    """负责将当前期切分为 10 章具体梗概 (🌟 支持动态软修正)"""
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

    print(f"📑 [Phase-Planner] 触发跨期推演！当前进入【{current_phase_name}】，正在提取本卷真实剧情碎片...")

    llm = get_llm(temperature=0.2)
    world_bible = state.get("world_bible_context", "")

    raw_volume_phases = state.get("current_volume_phases", "")
    focused_volume_phases = get_focused_volume_phases(raw_volume_phases, current_chapter_num)

    # 🌟 获取最新快照与本卷已发生的前几期回顾
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
        chapters_result: PhaseChapters = await _safe_json_invoke(
            llm, [
                SystemMessage(content=LAYER3_PHASE_PROMPT.format(
                    world_bible=world_bible,
                    volume_phases=focused_volume_phases,
                    history_context=history_context,
                    kv_snapshot=kv_snapshot,
                    previous_phase_summaries=prev_phases_text,
                    current_phase_name=current_phase_name
                )),
                HumanMessage(content="请结合真实的当前状态快照和本卷前情回顾，动态推演修正本期 10 章的具体梗概。")
            ],
            PhaseChapters, "Phase-Planner"
        )
        chapters_json = json.dumps(chapters_result.model_dump(), ensure_ascii=False, indent=2)

        if current_chapter_num > 1 and is_new_phase:
            print("🧹 [Phase-Planner] 动态新期推演成功！正在安全清理上一期的微观 RAG 碎片...")
            try:
                await asyncio.to_thread(RAGEngine(book_id=current_book_id).reset_phase_store)
            except Exception as e:
                pass

        return {"current_phase_chapters": chapters_json, "is_phase_initialized": True}
    except Exception as e:
        print(f"❌ [Phase-Planner] 单期大纲生成失败: {e}")
        return {"is_phase_initialized": False}


# ==========================================
# 📍 节点四：单章节拍拆解员 (Chapter/Beat Planner)
# ==========================================
async def chapter_planner_node(state: dict) -> Dict[str, Any]:
    """取代原有的 plot_planner_node，专注于生成微观 3-5 个节拍"""
    current_chapter_num = state.get("current_chapter_num", 1)
    current_book_id = state.get("book_id", "default_book")
    print(f"📍 [Chapter-Planner] 正在严格对齐本期十章梗概，拆解第 {current_chapter_num} 章节拍器...")

    latest_user_instruction = state.get("user_input", "")

    # 组装高优先级覆写文本
    human_override_instruction = ""
    if latest_user_instruction and latest_user_instruction.strip() and latest_user_instruction.strip() not in [
        "请按网文套路推进", ""]:
        human_override_instruction = (
            f"🔥【人类上帝指令 (God Command Override)】🔥\n"
            f"人类总编刚刚下达了本章的特定诉求：\n《{latest_user_instruction}》\n"
            f"🚨 警告：无论本章原本处于什么心流节奏（舒缓/高潮/悬疑），你都【必须绝对优先】满足总编的上述指令！系统节奏规则必须无条件让位于人类指令！\n"
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
            # 1. 优先执行 RAG Router 获取本章的实体关键词
            rag_router_llm = get_llm(temperature=0.1)
            rewriter_prompt = (
                f"你是一个RAG检索路由专家。当前准备写第 {current_chapter_num} 章。\n"
                f"【本期大纲参考】:\n{phase_chapters}\n\n"
                f"任务：请分析当前章的剧情重点，提取精准的关键词，并动态分配三层数据库的检索额度 K 值。\n"
                f"请直接输出一个完整的 JSON 对象，不要包裹在 markdown 代码块中，不要添加任何解释性文本。"
            )

            rag_plan: RAGQueryPlan = await _safe_json_invoke(
                rag_router_llm, [HumanMessage(content=rewriter_prompt)],
                RAGQueryPlan, "RAG-Router", max_retries=2, timeout=60
            )
            query_str = rag_plan.optimized_query

            print(
                f"   [🔍 RAG 智能路由] 关键词: {rag_plan.optimized_query} | K值分配: Global={rag_plan.k_global}, Volume={rag_plan.k_volume}, Phase={rag_plan.k_phase}")

            # 2. 🌟 执行异步 FAISS 检索
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

        # 3. 🌟 执行 On-Demand 按需召回快照
        filter_keywords = query_str.split() if query_str else []
        current_kv_state = await tracker.get_world_bible_snapshot(filter_entities=filter_keywords)

        # 获取未解决伏笔池
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

    # 🌟 修复队列读取：使用 recent_chapters_summary
    summary_list = state.get("recent_chapters_summary", [])
    recent_chapters_summary = "\n\n".join([f"【N-{len(summary_list) - i} 前情脉络】:\n{text}" for i, text in
                                           enumerate(summary_list)]) if summary_list else "（暂无前情提要）"

    # 注入系统级 Prompt
    sys_prompt = LAYER4_CHAPTER_PROMPT.format(
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
        planner_response: ChapterOutline = await _safe_json_invoke(
            llm, [
                SystemMessage(content=sys_prompt),
                HumanMessage(
                    content=f"请生成第 {current_chapter_num} 章节拍器。如果剧情合适，请优先从【未解伏笔/悬念/仇恨池】中挑选 1-2 个进行推进或彻底解决（填坑）。")
            ],
            ChapterOutline, "Chapter-Planner"
        )
        beat_sheet_json = json.dumps(planner_response.model_dump(), ensure_ascii=False, indent=2)

        return {
            "current_beat_sheet": beat_sheet_json,
            "rag_history_context": history_context
        }
    except Exception as e:
        print(f"❌ [Chapter-Planner] 节拍器生成失败: {e}")
        return {"current_beat_sheet": "（大纲生成异常，请主笔自由发挥）"}