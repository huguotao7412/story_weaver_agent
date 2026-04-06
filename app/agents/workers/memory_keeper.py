# app/agents/workers/memory_keeper.py
import os
from typing import Dict, Any, List
from pydantic import BaseModel, Field

from langchain_core.messages import HumanMessage, SystemMessage, RemoveMessage, AIMessage

from app.core.llm_factory import get_llm
from app.memory.kv_tracker import KVTracker
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
    item_name: str = Field(description="物品/法宝名称")
    action: str = Field(description="状态动作，必须是 ADD (获得/添加) 或 REMOVE (消耗/遗失)")
    description: str = Field(description="关于获得或消耗的具体描述")


class ResolvedThread(BaseModel):
    thread_id: int = Field(description="成功填上的伏笔坑的 ID (必须是系统提供的 ID 数字)")
    reason: str = Field(description="简述是如何解决的（例如：主角本章一剑斩杀了反派，大仇得报）")


class MemoryExtraction(BaseModel):
    map_update: MapUpdate = Field(description="主角宏观地图变更检测")
    character_updates: List[CharacterUpdate] = Field(default_factory=list, description="角色状态变更")
    item_updates: List[ItemUpdate] = Field(default_factory=list, description="物品状态变更")
    new_mysteries: List[str] = Field(default_factory=list,
                                     description="【挖坑】本章新挖的悬念坑、未解之谜、新结的死仇或长期约定（明确清晰的陈述）")
    resolved_mysteries: List[ResolvedThread] = Field(default_factory=list,
                                                     description="【填坑】对照现有的伏笔池，本章成功彻底解决掉的伏笔")
    global_events: List[str] = Field(default_factory=list, description="其他对世界观有影响的全局客观大事件")


# ==========================================
# 🧠 提示词定义区
# ==========================================
MEMORY_EXTRACTION_PROMPT = """你是一个专业的网文【记忆更新员】（Metadata Tracker）。
主笔刚刚完成了一章的定稿，你的任务是从这几千字的正文中，提取出对长线剧情有影响的“状态变更”与“伏笔更迭”。

【百万字长篇特殊指令】：
1. 🗺️ 换地图检测 (Map Update)：若跨越宏观大区域，务必触发。
2. 🔥 核心角色打标 (Core Character)：主角团/核心宠物设为 is_core=True。
3. 🕳️ 挖坑与填坑 (Foreshadowing & Mysteries)：这是长篇小说的灵魂！
   - 【挖坑】：如果本章主角惹了新的大敌、接了有时限的任务、发现了神秘未解的物品，请将其提取到 new_mysteries 中。
   - 【填坑】：我会提供一个【当前未解伏笔池】，如果本章的剧情彻底终结了池子中的某个伏笔（如杀死了仇人、赴了三年之约），请将其 ID 和解决方式提取到 resolved_mysteries 中。如果没有填坑，请留空。

请务必精准判断，不要将日常的小事当成大伏笔，也不要漏掉真正影响主线的大悬念。
"""


# ==========================================
# 🚀 核心节点逻辑
# ==========================================
async def memory_keeper_node(state: dict) -> Dict[str, Any]:
    print("🧠 [Memory-Keeper] 章节已获人类批准，正在提取定稿状态，同步至全局 KV 与伏笔池...")

    draft = state.get("draft_content", "")
    chapter_num = state.get("current_chapter_num", 1)
    messages = state.get("messages", [])
    current_book_id = state.get("book_id", "default_book")  # 🌟 提取书名 ID

    if not draft:
        return {}

    tracker = KVTracker(book_id=current_book_id)  # 🌟 隔离实例
    active_threads_snapshot = tracker.get_active_threads_snapshot()

    llm = get_llm(model_type="main", temperature=0.1)
    structured_llm = llm.with_structured_output(MemoryExtraction, method="function_calling")

    prompt_messages = [
        SystemMessage(content=MEMORY_EXTRACTION_PROMPT),
        HumanMessage(
            content=f"【当前未解伏笔池】(请对照填坑)：\n{active_threads_snapshot}\n\n【第 {chapter_num} 章定稿正文】：\n{draft}\n\n请提取状态变更与伏笔。")
    ]

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
            tracker.set_global_map(memory_updates.map_update.new_map_name)
            print(f"   [🗺️ 换地图触发] 主角跨越大地图至: {memory_updates.map_update.new_map_name}")

        for cu in memory_updates.character_updates:
            if cu.is_core: tracker.set_core_character(cu.name, is_core=True)
            tracker.update_character_state(cu.name, cu.key, cu.value, chapter_num)

        for iu in memory_updates.item_updates:
            tracker.update_inventory(iu.owner, iu.item_name, iu.action, chapter_num)

        for mystery in memory_updates.new_mysteries:
            tracker.add_unresolved_thread(mystery, chapter_num)
            print(f"   [🕳️ 挖坑登记] 发现新悬念/仇恨: {mystery}")

        valid_threads = tracker.threads_table.all()
        valid_ids = [t.doc_id for t in valid_threads]

        for resolved in memory_updates.resolved_mysteries:
            if resolved.thread_id in valid_ids:
                tracker.remove_resolved_thread(resolved.thread_id)
                print(f"   [✨ 填坑完成] 伏笔 [ID: {resolved.thread_id}] 已解决。原因: {resolved.reason}")
            else:
                print(f"   [🛡️ 幻觉防御] LLM 试图填一个不存在的伏笔 (ID: {resolved.thread_id})，已拦截。")

        rag_engine = RAGEngine(book_id=current_book_id)  # 🌟 隔离实例
        if memory_updates.global_events:
            rag_engine.insert_global_events(memory_updates.global_events, chapter_num)

        try:
            # 🌟 统一存放到本书的专属沙盒中
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

        prev_ending = draft[-300:] if len(draft) > 300 else draft

        return {
            "human_approval_status": "PENDING",
            "human_feedback": "",
            "previous_chapter_ending": prev_ending,
            "messages": delete_messages
        }

    except Exception as e:
        print(f"⚠️ [Memory-Keeper] 异常: {e}。")
        return {}