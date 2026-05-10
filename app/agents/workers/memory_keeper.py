# app/agents/workers/memory_keeper.py
import os
import json
import re
import asyncio
from typing import Dict, Any, List, Literal
from pydantic import BaseModel, Field

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.core.llm_factory import get_llm
from app.memory.kv_tracker import AsyncKVTracker
from app.memory.rag_engine import RAGEngine
from app.core.config import settings


# ==========================================
# 🌟 百万字长篇升级：Pydantic 结构化数据定义
# ==========================================
class MapUpdate(BaseModel):
    has_changed: bool = Field(
        description="本章主角是否彻底离开了旧区域，跨越到了新的【宏观大地图】（如从青云镇到了帝都、从凡人界飞升仙界）")
    new_map_name: str = Field(default="", description="如果发生跨越大地图，请填写新的地图名称；如果没有换地图，请留空")


class CharacterUpdate(BaseModel):
    name: str = Field(description="角色名字")
    key: str = Field(description="变更的属性名，如 status(死亡/存活), location(地理位置), level(境界/等级)")
    value: str = Field(description="变更后的值，例如：死亡、血色秘境、筑基期后期")
    reason: str = Field(description="导致变更的原因或情境描述")
    is_core: bool = Field(default=False, description="该角色是否属于【主角本人】或【绝对核心主角团】（跨地图不冻结）")


class ItemUpdate(BaseModel):
    owner: str = Field(description="物品的当前所有者")
    item_name: str = Field(description="物品、法宝、功法、或武技名称")
    action: str = Field(description="状态动作，必须是 ADD (获得/学会) 或 REMOVE (消耗/遗失/废除)")
    description: str = Field(description="关于获得或消耗的具体描述")


class ResolvedThread(BaseModel):
    thread_id: int = Field(description="成功填上的伏笔坑的 ID (必须是系统提供的 ID 数字)")
    reason: str = Field(description="简述是如何解决的（例如：主角本章一剑斩杀了反派，大仇得报）")


class NewThread(BaseModel):
    content: str = Field(description="伏笔/悬念/仇恨的具体描述")
    priority: Literal["High", "Medium", "Low"] = Field(
        description="High:生死大仇/主线; Medium:支线任务/长期约定; Low:日常小坑/未解物品")
    keywords: List[str] = Field(description="该伏笔涉及的2-3个核心实体关键词（人名/地名/物品）")
    related_map: str = Field(description="该伏笔绑定的宏观大地图名称，如果是贯穿全书的主线请填'全局'")


# 🌟 新增：世界观动态补丁
class WorldRuleUpdate(BaseModel):
    rule_name: str = Field(description="设定名称，如‘大荒剑意法则’、‘元婴期新特征’、‘新宗门背景’")
    description: str = Field(description="具体设定内容或新境界原理说明")
    category: Literal["功法原理", "天地法则", "新境界", "势力格局"] = Field(description="设定分类")


class MemoryExtraction(BaseModel):
    map_update: MapUpdate = Field(description="主角宏观地图变更检测")
    character_updates: List[CharacterUpdate] = Field(default_factory=list, description="角色状态变更")
    item_updates: List[ItemUpdate] = Field(default_factory=list, description="物品状态变更")
    new_mysteries: List[NewThread] = Field(default_factory=list,
                                           description="【挖坑】本章新挖的悬念坑、未解之谜、新结的死仇或长期约定。必须严格分类和打标！")
    resolved_mysteries: List[ResolvedThread] = Field(default_factory=list,
                                                     description="【填坑】对照现有的伏笔池，本章成功彻底解决掉的伏笔")
    world_rule_updates: List[WorldRuleUpdate] = Field(default_factory=list,
                                                      description="【世界观补丁】本章如果拓展了世界观、新境界、揭露了新背景，请提取为补丁")
    global_events: List[str] = Field(default_factory=list, description="其他对世界观有影响的全局客观大事件")


# ==========================================
# 🧠 提示词定义区 (🌟 增加补丁提取逻辑)
# ==========================================
MEMORY_EXTRACTION_PROMPT = """你是一个专业的网文【记忆更新员】（Metadata Tracker）。
主笔刚刚完成了一章的定稿，你的任务是从这几千字的正文中，提取出对长线剧情有影响的“状态变更”与“伏笔/设定更迭”。

【🚨 极其重要：境界数值拦截】：
参考当前战力体系：\n{power_system_rules}\n
如果本章出现角色境界变更，请务必校验其变更是否符合上述规则！绝不允许出现设定外的新境界！（除非明确是主角领悟/系统解锁的新体系，此时请放入补丁）

【百万字长篇特殊指令】：
1. 🗺️ 换地图检测 (Map Update)：若跨越宏观大区域，务必触发。
2. 🔥 核心角色打标 (Core Character)：主角团/核心宠物设为 is_core=True。
3. 🕳️ 挖坑与填坑 (Foreshadowing & Mysteries)：
   - 【挖坑】：惹了新大敌、接了新任务、结了新恩怨，必须打标为 new_mysteries，设定优先级和绑定地图！
   - 【填坑】：对照现有的伏笔池，解决掉的提取到 resolved_mysteries。
4. 📜 【世界观补丁 (World Bible Patching)】：如果本章主角领悟了全新的功法底层逻辑、世界抛出了新的力量体系（新境界），或揭露了上古势力的秘密，请将其提取为 `world_rule_updates`，让设定和世界观跟着剧情一起长大。

请务必精准判断，不要将日常的小事当成大伏笔或设定，也不要漏掉真正影响主线的大悬念。

请直接输出一个完整的 JSON 对象，不要包裹在 markdown 代码块中，不要添加任何解释性文本。
"""


# ==========================================
# 🚀 核心节点逻辑
# ==========================================
async def memory_keeper_node(state: dict) -> Dict[str, Any]:
    print("🧠 [Memory-Keeper] 章节已获人类批准，正在提取定稿状态，同步至全局 KV 与伏笔池...")

    draft_path = state.get("draft_path", "")
    draft = ""
    if draft_path and os.path.exists(draft_path):
        with open(draft_path, "r", encoding="utf-8") as f:
            draft = f.read()
    chapter_num = state.get("current_chapter_num", 1)
    current_book_id = state.get("book_id", "default_book")

    if not draft:
        return {}

    tracker = AsyncKVTracker(book_id=current_book_id)
    await tracker.init_db()
    current_map = await tracker.get_global_map()
    power_rules = await tracker.get_power_system_rules()
    active_threads_snapshot = await tracker.get_active_threads_snapshot(current_map=current_map)

    prompt_messages = [
        SystemMessage(content=MEMORY_EXTRACTION_PROMPT.format(power_system_rules=power_rules)),
        HumanMessage(
            content=f"【当前未解伏笔池】(请对照填坑)：\n{active_threads_snapshot}\n\n【第 {chapter_num} 章定稿正文】：\n{draft}\n\n请提取状态变更与伏笔。")
    ]

    llm = get_llm(temperature=0.1)

    memory_updates = None
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"⏳ [Memory-Keeper] 正在调用大模型提取状态 (第 {attempt + 1}/{max_retries} 次)...")
            response = await asyncio.wait_for(llm.ainvoke(prompt_messages), timeout=180)

            content = response.content
            m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
            json_str = m.group(1).strip() if m else content.strip()
            if not json_str.startswith('{'):
                m2 = re.search(r'\{.*\}', content, re.DOTALL)
                if m2:
                    json_str = m2.group(0).strip()

            memory_updates = MemoryExtraction.model_validate_json(json_str)
            break
        except Exception as e:
            print(f"⚠️ [Memory-Keeper] 第 {attempt + 1} 次解析状态失败: {e}")
            if attempt < max_retries - 1:
                prompt_messages.append(AIMessage(content="你的输出格式有误，导致 JSON 解析失败。"))
                prompt_messages.append(HumanMessage(
                    content=f"这是报错信息：{str(e)}\n请检查必填字段是否遗漏，并严格遵守 JSON Schema 重新输出，不要附加任何说明文字。"))

    if not memory_updates:
        print("❌ [Memory-Keeper] 连续 3 次提取状态失败，放弃本次状态更新，强制入库防卡死。")
        return {"human_approval_status": "PENDING", "human_feedback": ""}

    try:
        # --- KV 存储更新 ---
        if memory_updates.map_update.has_changed and memory_updates.map_update.new_map_name:
            await tracker.set_global_map(memory_updates.map_update.new_map_name)
            print(f"   [🗺️ 换地图触发] 主角跨越大地图至: {memory_updates.map_update.new_map_name}")

        for cu in memory_updates.character_updates:
            if cu.is_core: await tracker.set_core_character(cu.name, is_core=True)
            await tracker.update_character_state(cu.name, cu.key, cu.value, chapter_num)

        for iu in memory_updates.item_updates:
            await tracker.update_inventory(iu.owner, iu.item_name, iu.action, chapter_num)

        for mystery in memory_updates.new_mysteries:
            mystery_dict = mystery.model_dump()
            await tracker.add_unresolved_thread(mystery_dict, chapter_num)
            print(f"   [🕳️ 挖坑登记] 发现新悬念/仇恨 [{mystery_dict['priority']}]: {mystery_dict['content']}")

        for resolved in memory_updates.resolved_mysteries:
            await tracker.remove_resolved_thread(resolved.thread_id)
            print(f"   [✨ 填坑完成] 尝试解决伏笔 [ID: {resolved.thread_id}]。原因: {resolved.reason}")

        # 🌟 应用世界观补丁
        for patch in memory_updates.world_rule_updates:
            patch_dict = patch.model_dump()
            await tracker.append_world_rule_patch(patch_dict)
            print(f"   [📜 设定进化] 捕获世界观补丁 [{patch_dict['category']}]: {patch_dict['rule_name']}")

        rag_engine = RAGEngine(book_id=current_book_id)
        if memory_updates.global_events:
            await asyncio.to_thread(rag_engine.insert_global_events, memory_updates.global_events, chapter_num)

        try:
            archive_dir = os.path.join(settings.DATA_DIR, current_book_id, "chapter_archive")
            os.makedirs(archive_dir, exist_ok=True)
            file_name = f"chapter_{chapter_num:03d}.md"
            file_path = os.path.join(archive_dir, file_name)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"# 第 {chapter_num} 章\n\n{draft}")
        except Exception as e:
            pass

        prev_ending = draft[-500:] if len(draft) > 500 else draft

        # ==========================================
        # 🌟 层级化摘要核心逻辑 (统一使用 main 模型)
        # ==========================================
        main_llm = get_llm(temperature=0.1)

        print("📝 [Memory-Keeper] 正在生成本章 200 字核心摘要...")
        summary_prompt = f"请将以下这章网文正文压缩为200字的核心剧情摘要。只保留最关键的动作、结果和结尾的悬念，去掉废话和景色描写：\n{draft}"
        try:
            summary_msg = await main_llm.ainvoke([HumanMessage(content=summary_prompt)])
            current_summary_text = summary_msg.content.strip()
            print("✅ [Memory-Keeper] 单章摘要生成成功入库！")
            await tracker.save_chapter_summary(chapter_num, current_summary_text)

            # 🌟 将本章细节灌入 Volume 和 Phase RAG 库，确保层级检索有数据可查
            try:
                chapter_events = [current_summary_text]
                if len(draft) > 200:
                    chapter_events.append(draft[:200] + "...")  # 附带正文开头片段增强语义检索
                await asyncio.to_thread(rag_engine.insert_chapter_details, chapter_events, chapter_num)
            except Exception as e:
                print(f"⚠️ [Memory-Keeper] RAG 章节细节入库失败: {e}")
        except Exception as e:
            print(f"⚠️ [Memory-Keeper] 单章摘要生成失败: {e}")
            current_summary_text = "（本章摘要生成失败）"
            await tracker.save_chapter_summary(chapter_num, current_summary_text)

        # 维护双章滚动摘要 (用于提供给主笔的短期衔接)
        old_summary_raw = state.get("recent_chapters_summary", [])
        old_summary = list(old_summary_raw) if isinstance(old_summary_raw, list) else []
        old_summary.append(f"第 {chapter_num} 章: {current_summary_text}")
        rolling_summary = old_summary[-2:]

        # 🌟 逢十归一：单期压缩 (Phase Summary)
        if chapter_num % 10 == 0:
            current_phase = chapter_num // 10
            print(f"📝 [Memory-Keeper] 触发【单期摘要】压缩：正在归纳第 {current_phase} 期大事件...")
            start_ch = chapter_num - 9
            phase_chapters_text_list = await tracker.get_chapter_summaries(start_ch, chapter_num)
            phase_chapters_text = "\n".join(phase_chapters_text_list)

            phase_summary_prompt = f"你是一个网文主编。以下是本书第 {start_ch} 章到第 {chapter_num} 章的各章剧情摘要：\n{phase_chapters_text}\n\n请将这10章的剧情浓缩为一份500字的《单期核心脉络总结》。重点保留主角的核心冲突转移、境界变化、重要法宝获得以及人物关系的重大改变。"
            try:
                phase_summary_msg = await main_llm.ainvoke([HumanMessage(content=phase_summary_prompt)])
                await tracker.save_phase_summary(current_phase, phase_summary_msg.content.strip())
                print(f"✅ [Memory-Keeper] 第 {current_phase} 期宏观脉络总结完成入库！")
            except Exception as e:
                print(f"⚠️ [Memory-Keeper] 单期摘要压缩失败: {e}")

        # 🌟 逢五十归一：单卷压缩 (Volume Summary)
        if chapter_num % 50 == 0:
            current_volume = chapter_num // 50
            print(f"📝 [Memory-Keeper] 触发【单卷摘要】终极压缩：正在归纳第 {current_volume} 卷史诗剧情...")
            start_phase = (current_volume - 1) * 5 + 1
            end_phase = current_volume * 5
            volume_phases_text_list = await tracker.get_phase_summaries(start_phase, end_phase)
            volume_phases_text = "\n\n".join(volume_phases_text_list)

            volume_summary_prompt = f"你是一个白金网文大帝。以下是本书第 {current_volume} 卷（共50章，5个期）的分期核心脉络总结：\n{volume_phases_text}\n\n请将这一整卷的剧情浓缩为一份800字的《本卷剧情终极回顾》。必须讲清楚：本卷起因、核心大高潮是怎样打的、击杀了什么重要敌人、主角获得了什么底牌，以及本卷结尾留向下一卷的钩子。"
            try:
                volume_summary_msg = await main_llm.ainvoke([HumanMessage(content=volume_summary_prompt)])
                await tracker.save_volume_summary(current_volume, volume_summary_msg.content.strip())
                print(f"✅ [Memory-Keeper] 第 {current_volume} 卷剧情终极回顾完成入库！")
            except Exception as e:
                print(f"⚠️ [Memory-Keeper] 单卷摘要压缩失败: {e}")

        return {
            "human_approval_status": "PENDING",
            "human_feedback": "",
            "previous_chapter_ending": prev_ending,
            "recent_chapters_summary": rolling_summary,
            "revision_history": [],
            "current_beat_sheet": "",
            "draft_path": ""
        }

    except Exception as e:
        print(f"⚠️ [Memory-Keeper] 异常: {e}。")
        # 即使 Memory_Keeper 整体失败，也要尽力传递正确的上一章结尾和摘要
        fallback_ending = draft[-500:] if draft and len(draft) > 500 else (draft or "")
        old_summary_raw = state.get("recent_chapters_summary", [])
        fallback_summary = list(old_summary_raw) if isinstance(old_summary_raw, list) else []
        return {
            "previous_chapter_ending": fallback_ending,
            "recent_chapters_summary": fallback_summary,
            "revision_history": [],
            "current_beat_sheet": "",
            "draft_path": "",
            "human_approval_status": "PENDING",
            "human_feedback": ""
        }