# app/agents/workers/memory_keeper.py
import os
import json
import asyncio
from typing import Dict, Any, List, Literal

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from app.agents.base import BaseAgent
from app.core.llm_factory import get_llm
from app.memory.kv_tracker import AsyncKVTracker
from app.memory.rag_engine import RAGEngine
from app.core.config import settings
from app.agents.registry import register


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


class WorldRuleUpdate(BaseModel):
    rule_name: str = Field(description="设定名称，如'大荒剑意法则'、'元婴期新特征'、'新宗门背景'")
    description: str = Field(description="具体设定内容或新境界原理说明")
    category: Literal["功法原理", "天地法则", "新境界", "势力格局"] = Field(description="设定分类")


class EntityExtraction(BaseModel):
    """专家 A：专精实体追踪（地图变更、角色状态、物品流转）"""
    map_update: MapUpdate = Field(description="主角宏观地图变更检测")
    character_updates: List[CharacterUpdate] = Field(default_factory=list, description="角色状态变更")
    item_updates: List[ItemUpdate] = Field(default_factory=list, description="物品状态变更")


class PlotThreadExtraction(BaseModel):
    """专家 B：专精伏笔与悬念追踪（挖坑与填坑）"""
    new_mysteries: List[NewThread] = Field(default_factory=list,
                                           description="【挖坑】本章新挖的悬念坑、未解之谜、新结的死仇或长期约定。必须严格分类和打标！")
    resolved_mysteries: List[ResolvedThread] = Field(default_factory=list,
                                                     description="【填坑】对照现有的伏笔池，本章成功彻底解决掉的伏笔")


class WorldLoreExtraction(BaseModel):
    """专家 C：专精世界观与大事件追踪（设定补丁、全局事件）"""
    world_rule_updates: List[WorldRuleUpdate] = Field(default_factory=list,
                                                      description="【世界观补丁】本章如果拓展了世界观、新境界、揭露了新背景，请提取为补丁")
    global_events: List[str] = Field(default_factory=list, description="其他对世界观有影响的全局客观大事件")


class MemoryKeeperAgent(BaseAgent):
    name = "Memory_Keeper"
    prompt_file = "memory_keeper.yaml"

    async def execute(self, state: dict) -> Dict[str, Any]:
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

        base_messages = self.load_prompt(power_system_rules=power_rules)

        # 为三个专家分别构建专用消息（拷贝 base_messages 避免并发修改冲突）
        entity_messages = list(base_messages) + [HumanMessage(
            content=(
                f"【第 {chapter_num} 章定稿正文】：\n{draft}\n\n"
                f"【当前大地图】：{current_map}\n"
                f"请专注提取：地图是否切换、角色状态变更（含 is_core 标记）、物品流转（ADD/REMOVE）。"
            )
        )]
        thread_messages = list(base_messages) + [HumanMessage(
            content=(
                f"【当前未解伏笔池】(请对照填坑)：\n{active_threads_snapshot}\n\n"
                f"【第 {chapter_num} 章定稿正文】：\n{draft}\n\n"
                f"请专注提取：新挖的悬念坑（new_mysteries）和已解决的伏笔（resolved_mysteries）。"
            )
        )]
        lore_messages = list(base_messages) + [HumanMessage(
            content=(
                f"【第 {chapter_num} 章定稿正文】：\n{draft}\n\n"
                f"请专注提取：世界观设定补丁（新境界/新法则/新势力格局）和全局客观大事件。"
            )
        )]

        llm = get_llm(temperature=0.1)

        try:
            print("🧠 [Memory-Keeper] 正在并发启动：实体追踪、伏笔分析、世界观提取...")
            entity_task = self.safe_json_invoke(llm, entity_messages, EntityExtraction, max_retries=3)
            thread_task = self.safe_json_invoke(llm, thread_messages, PlotThreadExtraction, max_retries=3)
            lore_task = self.safe_json_invoke(llm, lore_messages, WorldLoreExtraction, max_retries=3)

            results = await asyncio.gather(
                entity_task, thread_task, lore_task, return_exceptions=True
            )

            # 独立解析并容错
            if isinstance(results[0], Exception):
                print(f"⚠️ [Memory-Keeper] 实体提取异常: {results[0]}")
                entity_res = EntityExtraction(map_update=MapUpdate(has_changed=False, new_map_name=""))
            else:
                entity_res = results[0]

            if isinstance(results[1], Exception):
                print(f"⚠️ [Memory-Keeper] 伏笔提取异常: {results[1]}")
                thread_res = PlotThreadExtraction()
            else:
                thread_res = results[1]

            if isinstance(results[2], Exception):
                print(f"⚠️ [Memory-Keeper] 世界观提取异常: {results[2]}")
                lore_res = WorldLoreExtraction()
            else:
                lore_res = results[2]
            print("✅ [Memory-Keeper] 三路专家记忆提取成功！")
        except Exception as e:
            print(f"❌ [Memory-Keeper] 严重异常: {e}")
            return {"human_approval_status": "PENDING", "human_feedback": ""}

        try:
            # 1. 跨地图检测
            if entity_res.map_update.has_changed and entity_res.map_update.new_map_name:
                await tracker.set_global_map(entity_res.map_update.new_map_name)
                print(f"   [🗺️ 换地图触发] 主角跨越大地图至: {entity_res.map_update.new_map_name}")

            # 2. 批量处理角色更新
            char_updates_payload = []
            for cu in entity_res.character_updates:
                    if cu.is_core:
                        await tracker.set_core_character(cu.name, is_core=True)
                    char_updates_payload.append({
                        "name": cu.name, "key": cu.key,
                        "value": cu.value, "chapter_num": chapter_num
                    })
            if char_updates_payload:
                    await tracker.batch_update_character_states(char_updates_payload)

            # 3. 批量处理物品更新
            inventory_updates_payload = []
            for iu in entity_res.item_updates:
                    inventory_updates_payload.append({
                        "owner": iu.owner, "item_name": iu.item_name,
                        "action": iu.action, "chapter_num": chapter_num
                    })
            if inventory_updates_payload:
                    await tracker.batch_update_inventory(inventory_updates_payload)

            # 4. 批量处理新伏笔 (挖坑)
            threads_payload = []
            for mystery in thread_res.new_mysteries:
                    threads_payload.append(mystery.model_dump())
                    print(f"   [🕳️ 挖坑登记] 发现新悬念/仇恨 [{mystery.priority}]: {mystery.content}")
            if threads_payload:
                    await tracker.batch_add_unresolved_threads(threads_payload, chapter_num)

            # 5. 填坑依然用循环
            for resolved in thread_res.resolved_mysteries:
                    await tracker.remove_resolved_thread(resolved.thread_id)
                    print(f"   [✨ 填坑完成] 尝试解决伏笔 [ID: {resolved.thread_id}]。原因: {resolved.reason}")

            # 6. 世界观补丁
            for patch in lore_res.world_rule_updates:
                    patch_dict = patch.model_dump()
                    await tracker.append_world_rule_patch(patch_dict)
                    print(f"   [📜 设定进化] 捕获世界观补丁 [{patch_dict['category']}]: {patch_dict['rule_name']}")

            rag_engine = RAGEngine(book_id=current_book_id)
            if lore_res.global_events:
                await asyncio.to_thread(rag_engine.insert_global_events, lore_res.global_events, chapter_num)

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

            main_llm = get_llm(temperature=0.1)

            print("📝 [Memory-Keeper] 正在生成本章 200 字核心摘要...")
            summary_prompt = f"请将以下这章网文正文压缩为200字的核心剧情摘要。只保留最关键的动作、结果和结尾的悬念，去掉废话和景色描写：\n{draft}"
            try:
                summary_msg = await main_llm.ainvoke([HumanMessage(content=summary_prompt)])
                current_summary_text = summary_msg.content.strip()
                print("✅ [Memory-Keeper] 单章摘要生成成功入库！")
                await tracker.save_chapter_summary(chapter_num, current_summary_text)

                try:
                    chapter_events = [current_summary_text]
                    if len(draft) > 200:
                        chapter_events.append(draft[:200] + "...")
                    await asyncio.to_thread(rag_engine.insert_chapter_details, chapter_events, chapter_num)
                except Exception as e:
                    print(f"⚠️ [Memory-Keeper] RAG 章节细节入库失败: {e}")
            except Exception as e:
                print(f"⚠️ [Memory-Keeper] 单章摘要生成失败: {e}")
                current_summary_text = "（本章摘要生成失败）"
                await tracker.save_chapter_summary(chapter_num, current_summary_text)

            old_summary_raw = state.get("recent_chapters_summary", [])
            old_summary = list(old_summary_raw) if isinstance(old_summary_raw, list) else []
            old_summary.append(f"第 {chapter_num} 章: {current_summary_text}")
            rolling_summary = old_summary[-2:]

            if chapter_num % 10 == 0:
                current_phase = (chapter_num - 1) // 10 + 1
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

            if chapter_num % 50 == 0:
                current_volume = (chapter_num - 1) // 50 + 1
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

            # 清理本章临时上下文
            await tracker.save_temp_context("beat_sheet", "")
            await tracker.save_temp_context("rag_history", "")

            return {
                "human_approval_status": "PENDING",
                "human_feedback": "",
                "previous_chapter_ending": prev_ending,
                "recent_chapters_summary": rolling_summary,
                "revision_history": [],
                "draft_path": ""
            }

        except Exception as e:
            print(f"⚠️ [Memory-Keeper] 异常: {e}。")
            fallback_ending = draft[-500:] if draft and len(draft) > 500 else (draft or "")
            old_summary_raw = state.get("recent_chapters_summary", [])
            fallback_summary = list(old_summary_raw) if isinstance(old_summary_raw, list) else []
            return {
                "previous_chapter_ending": fallback_ending,
                "recent_chapters_summary": fallback_summary,
                "revision_history": [],
                "draft_path": "",
                "human_approval_status": "PENDING",
                "human_feedback": ""
            }


@register("memory_keeper")
async def memory_keeper_node(state: dict) -> Dict[str, Any]:
    agent = MemoryKeeperAgent()
    return await agent.execute(state)
