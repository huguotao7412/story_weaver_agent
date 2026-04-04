# 🧠 记忆更新员：提取定稿状态，更新全局 KV 与 RAG 数据库
# 职责：【数据库写入节点】提炼定稿章节中的状态变更（如：获得神器、配角死亡），动态更新至全局。
# 参考实现：脱离 LLM 上下文窗口限制，利用外部 KV 数据库追踪长线 Metadata。
# app/agents/workers/memory_keeper.py
import os
from typing import Dict, Any, List
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import get_llm
from app.memory.kv_tracker import KVTracker
from app.memory.rag_engine import RAGEngine
from app.core.config import settings


# ==========================================
# 🌟 Pydantic 结构化数据定义
# ==========================================
class CharacterUpdate(BaseModel):
    name: str = Field(description="角色名字")
    key: str = Field(description="变更的属性名，如 status(死亡/存活), location(地理位置), level(境界/等级)")
    value: str = Field(description="变更后的值，例如：死亡、血色秘境、筑基期后期")
    reason: str = Field(description="导致变更的原因或情境描述")


class ItemUpdate(BaseModel):
    owner: str = Field(description="物品的当前所有者")
    item_name: str = Field(description="物品/法宝名称")
    action: str = Field(description="状态动作，必须是 ADD (获得/添加) 或 REMOVE (消耗/遗失)")
    description: str = Field(description="关于获得或消耗的具体描述")


class MemoryExtraction(BaseModel):
    character_updates: List[CharacterUpdate] = Field(default_factory=list, description="角色状态变更列表，若无则为空")
    item_updates: List[ItemUpdate] = Field(default_factory=list, description="物品状态变更列表，若无则为空")
    global_events: List[str] = Field(default_factory=list, description="对长线剧情有重大影响的全局客观事件列表")


# ==========================================
# 🧠 提示词定义区
# ==========================================
MEMORY_EXTRACTION_PROMPT = """你是一个专业的网文【记忆更新员】（Metadata Tracker）。
主笔刚刚完成了一章的定稿，你的任务是从这几千字的正文中，提取出对长线剧情有影响的关键“状态变更”。

为了脱离 LLM 有限的上下文窗口，我们需要将角色的核心状态持久化到 KV 数据库中。
请重点提取以下维度的变更（如果没有则留空）：
1. 角色状态 (Character States)：包括死亡、重伤、境界/等级突破、位置转移等。
2. 物品/法宝 (Items & Artifacts)：重要道具的获得、消耗、遗失或转交。
3. 全局事件 (Global Events)：重大剧情推进或世界法则更替。

注意：
- 提取的信息必须是**刚刚发生的、明确的客观事实**，不要提取心理活动或毫无根据的猜测。
- 如果本章全是日常对话，没有任何核心状态变更，相应的数组应保持为空。
"""


# ==========================================
# 🚀 核心节点逻辑
# ==========================================
def memory_keeper_node(state: dict) -> Dict[str, Any]:
    """
    🧠 Memory-Keeper (记忆更新员)
    """
    print("🧠 [Memory-Keeper] 章节已获人类批准，正在提取定稿状态，同步至全局 KV 数据库...")

    draft = state.get("draft_content", "")
    chapter_num = state.get("current_chapter_num", 1)

    if not draft:
        print("⚠️ [Memory-Keeper] 未检测到定稿内容，跳过记忆更新。")
        return {}

    llm = get_llm(model_type="main", temperature=0.1)

    # 🌟 核心改造：使用结构化输出引擎
    structured_llm = llm.with_structured_output(MemoryExtraction)

    messages = [
        SystemMessage(content=MEMORY_EXTRACTION_PROMPT),
        HumanMessage(content=f"【第 {chapter_num} 章定稿正文】：\n{draft}\n\n请提取状态变更。")
    ]

    try:
        # 直接获取 Pydantic 对象，彻底杜绝 JSON 解析错误
        memory_updates: MemoryExtraction = structured_llm.invoke(messages)

        # 初始化 KV 数据库追踪器
        tracker = KVTracker()

        # 1. 写入角色状态更新
        for cu in memory_updates.character_updates:
            tracker.update_character_state(
                name=cu.name,
                key=cu.key,
                value=cu.value,
                chapter_num=chapter_num
            )
            print(f"   [KV写入] 角色 {cu.name} -> {cu.key}: {cu.value}")

        # 2. 写入物品状态更新
        for iu in memory_updates.item_updates:
            tracker.update_inventory(
                owner=iu.owner,
                item_name=iu.item_name,
                action=iu.action,
                chapter_num=chapter_num
            )
            print(f"   [KV写入] 物品 {iu.item_name} ({iu.action}) -> 所属: {iu.owner}")

        # 3. 写入全局历史事件 RAG 库
        rag_engine = RAGEngine()
        if memory_updates.global_events:
            rag_engine.insert_events(memory_updates.global_events, chapter_num)

        print(f"✅ [Memory-Keeper] 第 {chapter_num} 章核心数据持久化完成。上下文窗口压力已释放。")

        # 4. 物理归档落盘 Markdown
        try:
            file_name = f"chapter_{chapter_num:03d}.md"
            file_path = os.path.join(settings.CHAPTER_ARCHIVE_DIR, file_name)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"# 第 {chapter_num} 章\n\n")
                f.write(draft)

            print(f"   [文本归档] 章节正文已成功归档至: {file_path}")
        except Exception as e:
            print(f"⚠️ [Memory-Keeper] 章节 Markdown 归档失败: {e}")

        # 记忆更新完毕，重置人类审批状态，准备进入下一章流转
        return {
            "human_approval_status": "PENDING",
            "human_feedback": ""
        }

    except Exception as e:
        print(f"⚠️ [Memory-Keeper] 结构化输出或写入异常: {e}。本次记忆追踪跳过，但流转继续。")
        return {}