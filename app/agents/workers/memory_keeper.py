# app/agents/workers/memory_keeper.py
import os
from typing import Dict, Any, List, Literal
from pydantic import BaseModel, Field

from langchain_core.messages import HumanMessage, SystemMessage, RemoveMessage, AIMessage

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
    item_name: str = Field(description="物品、法宝、功法、或武技名称")  # 强调功法
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


class MemoryExtraction(BaseModel):
    map_update: MapUpdate = Field(description="主角宏观地图变更检测")
    character_updates: List[CharacterUpdate] = Field(default_factory=list, description="角色状态变更")
    item_updates: List[ItemUpdate] = Field(default_factory=list, description="物品状态变更")
    new_mysteries: List[NewThread] = Field(default_factory=list,
                                           description="【挖坑】本章新挖的悬念坑、未解之谜、新结的死仇或长期约定。必须严格分类和打标！")

    resolved_mysteries: List[ResolvedThread] = Field(default_factory=list,
                                                     description="【填坑】对照现有的伏笔池，本章成功彻底解决掉的伏笔")
    global_events: List[str] = Field(default_factory=list, description="其他对世界观有影响的全局客观大事件")


# ==========================================
# 🧠 提示词定义区
# ==========================================
MEMORY_EXTRACTION_PROMPT = """你是一个专业的网文【记忆更新员】（Metadata Tracker）。
主笔刚刚完成了一章的定稿，你的任务是从这几千字的正文中，提取出对长线剧情有影响的“状态变更”与“伏笔更迭”。

【🚨 极其重要：境界数值拦截】：
参考当前战力体系：\n{power_system_rules}\n
如果本章出现角色境界变更，请务必校验其变更是否符合上述规则！绝不允许出现设定外的新境界！

【百万字长篇特殊指令】：
1. 🗺️ 换地图检测 (Map Update)：若跨越宏观大区域，务必触发。
2. 🔥 核心角色打标 (Core Character)：主角团/核心宠物设为 is_core=True。
3. 🕳️ 挖坑与填坑 (Foreshadowing & Mysteries)：
   - 【挖坑】：如果本章主角惹了新的大敌、接了任务，请将其提取为 new_mysteries，并严格评估其优先级(High/Medium/Low)和绑定地图！
   - 【恩怨登记】：如果本章主角救了某人或结了新的死仇，即使对方逃跑，也必须将其作为 High/Medium 级别的伏笔登记在案，明确标注【仇家/恩人】关系，以防未来再遇时模型产生 OOC。
   - 【填坑】：对照现有的伏笔池，解决掉的提取到 resolved_mysteries 中。

请务必精准判断，不要将日常的小事当成大伏笔，也不要漏掉真正影响主线的大悬念。
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
    messages = state.get("messages", [])
    current_book_id = state.get("book_id", "default_book")

    if not draft:
        return {}

    tracker = AsyncKVTracker(book_id=current_book_id)
    await tracker.init_db()  # 必须初始化
    current_map = await tracker.get_global_map()
    power_rules = await tracker.get_power_system_rules()
    active_threads_snapshot = await tracker.get_active_threads_snapshot(current_map=current_map)

    prompt_messages = [
        SystemMessage(content=MEMORY_EXTRACTION_PROMPT.format(power_system_rules=power_rules)),
        HumanMessage(
            content=f"【当前未解伏笔池】(请对照填坑)：\n{active_threads_snapshot}\n\n【第 {chapter_num} 章定稿正文】：\n{draft}\n\n请提取状态变更与伏笔。")
    ]

    llm = get_llm(model_type="main", temperature=0.1)
    structured_llm = llm.with_structured_output(MemoryExtraction, method="function_calling")

    memory_updates = None
    max_retries = 3
    for attempt in range(max_retries):
        try:
            memory_updates = await structured_llm.ainvoke(prompt_messages)
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

        # 🌟 修复点：移除了 TinyDB 遗留的 tracker.threads_table.all() 语法，直接利用 aiosqlite 进行操作
        for resolved in memory_updates.resolved_mysteries:
            await tracker.remove_resolved_thread(resolved.thread_id)
            print(f"   [✨ 填坑完成] 尝试解决伏笔 [ID: {resolved.thread_id}]。原因: {resolved.reason}")

        rag_engine = RAGEngine(book_id=current_book_id)
        if memory_updates.global_events:
            rag_engine.insert_global_events(memory_updates.global_events, chapter_num)

        try:
            archive_dir = os.path.join(settings.DATA_DIR, current_book_id, "chapter_archive")
            os.makedirs(archive_dir, exist_ok=True)
            file_name = f"chapter_{chapter_num:03d}.md"
            file_path = os.path.join(archive_dir, file_name)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"# 第 {chapter_num} 章\n\n{draft}")
        except Exception as e:
            pass

        delete_messages = []
        if len(messages) > 2:
            for msg in messages[:-2]:
                if hasattr(msg, "id") and msg.id: delete_messages.append(RemoveMessage(id=msg.id))

        prev_ending = draft[-500:] if len(draft) > 500 else draft

        # ==========================================
        # 🌟 双章滚动摘要核心逻辑 (Tapered Context)
        # ==========================================
        print("📝 [Memory-Keeper] 正在生成本章 200 字核心摘要...")

        # 1. 安全提取系统中保留的“旧摘要”
        old_summary_raw = state.get("recent_chapter_summary", "")
        old_summary_clean = ""

        # 如果旧摘要已经是双章拼接格式，提取其 N-1 部分，使之在下一轮变成 N-2
        if "【N-1 刚刚发生的事" in old_summary_raw:
            try:
                # 提取上一章的内容块
                old_summary_clean = old_summary_raw.split("【N-1 刚刚发生的事")[1].split("】:\n")[-1].strip()
            except:
                old_summary_clean = old_summary_raw[-400:]
        else:
            old_summary_clean = old_summary_raw.replace("（暂无前情提要）", "").replace(
                "（摘要生成失败，请依赖大纲与碎片历史进行推演）", "").strip()
            if len(old_summary_clean) > 400:
                old_summary_clean = old_summary_clean[-400:]  # 保底长度截断

        # 2. 调用小模型生成“本章”摘要
        summary_prompt = f"请将以下这章网文正文压缩为200字的核心剧情摘要。只保留最关键的动作、结果和结尾的悬念，去掉废话和景色描写：\n{draft}"
        fast_llm = get_llm(model_type="fast", temperature=0.1)  # 推荐使用便宜且速度快的小模型

        try:
            summary_msg = await fast_llm.ainvoke([HumanMessage(content=summary_prompt)])
            current_summary_text = summary_msg.content.strip()
            print("✅ [Memory-Keeper] 摘要生成成功！")
        except Exception as e:
            print(f"⚠️ [Memory-Keeper] 摘要生成失败: {e}")
            current_summary_text = "（本章摘要生成失败）"

        # 3. 滚动拼接：将提取出的 N-2 与刚刚生成的 N-1 合成最终的连载脉络
        if old_summary_clean:
            rolling_summary = f"【N-2 之前剧情脉络】:\n{old_summary_clean}\n\n【N-1 刚刚发生的事 (第{chapter_num}章)】:\n{current_summary_text}"
        else:
            rolling_summary = f"【N-1 刚刚发生的事 (第{chapter_num}章)】:\n{current_summary_text}"

        return {
            "human_approval_status": "PENDING",
            "human_feedback": "",
            "previous_chapter_ending": prev_ending,
            "recent_chapter_summary": rolling_summary,  # 🌟 写入拼装好的双章滚动摘要
            "messages": delete_messages,
            "current_beat_sheet": "",
            "draft_path": ""
        }

    except Exception as e:
        print(f"⚠️ [Memory-Keeper] 异常: {e}。")
        return {}