# 🧠 记忆更新员：提取定稿状态，更新全局 KV 与 RAG 数据库
# 职责：【数据库写入节点】提炼定稿章节中的状态变更（如：获得神器、配角死亡），动态更新至全局。
# 参考实现：脱离 LLM 上下文窗口限制，利用外部 KV 数据库追踪长线 Metadata。
# app/agents/workers/memory_keeper.py
import os
import json
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import get_llm
from app.memory.kv_tracker import KVTracker
from app.memory.rag_engine import RAGEngine
from app.core.config import settings

# ==========================================
# 🧠 提示词定义区：非结构化文本转结构化 KV
# ==========================================
MEMORY_EXTRACTION_PROMPT = """你是一个专业的网文【记忆更新员】（Metadata Tracker）。
主笔刚刚完成了一章的定稿，你的任务是从这几千字的正文中，提取出对长线剧情有影响的关键“状态变更”。

为了脱离 LLM 有限的上下文窗口，我们需要将角色的核心状态持久化到 KV 数据库中。
请重点提取以下维度的变更（如果没有则留空）：
1. 角色状态 (Character States)：包括死亡、重伤、境界/等级突破、位置转移等。
2. 物品/法宝 (Items & Artifacts)：重要道具的获得、消耗、遗失或转交。
3. 关系/阵营 (Relationships)：角色之间好感度的重大转变，或结仇/结盟。

请仔细阅读【定稿正文】，并以严格的 JSON 格式输出状态变更清单。数据结构必须如下：
{{
    "character_updates": [
        {{"name": "张三", "key": "status", "value": "死亡", "reason": "在后山被李四击杀"}},
        {{"name": "李四", "key": "location", "value": "血色秘境", "reason": "进入副本探险"}},
        {{"name": "李四", "key": "level", "value": "筑基期后期", "reason": "服用破阶丹突破"}}
    ],
    "item_updates": [
        {{"owner": "李四", "item_name": "屠龙宝刀", "action": "ADD", "description": "在秘境宝箱中开出"}},
        {{"owner": "王五", "item_name": "替身草人", "action": "REMOVE", "description": "抵挡致命一击后损毁"}}
    ],
    "global_events": [
        "血色秘境正式开启，持续时间一个月"
    ]
}}

注意：
- 提取的信息必须是**刚刚发生的、明确的客观事实**，不要提取心理活动或毫无根据的猜测。
- 如果本章全是日常对话，没有任何核心状态变更，相应的数组可以为空 `[]`。
- 只输出合法 JSON，不要包含 Markdown 代码块标记（如 ```json）。
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

    # 使用主模型（如 GPT-4o / DeepSeek-V2），低温度确保格式稳定和事实提取准确
    llm = get_llm(model_type="main", temperature=0.1)

    messages = [
        SystemMessage(content=MEMORY_EXTRACTION_PROMPT),
        HumanMessage(content=f"【第 {chapter_num} 章定稿正文】：\n{draft}\n\n请提取状态变更并输出 JSON。")
    ]

    try:
        response = llm.invoke(messages)
        content = response.content.strip()

        # 清理 JSON Markdown 标签
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        memory_updates = json.loads(content)

        # 初始化 KV 数据库追踪器
        tracker = KVTracker()

        # 1. 写入角色状态更新
        char_updates = memory_updates.get("character_updates", [])
        for cu in char_updates:
            tracker.update_character_state(
                name=cu["name"],
                key=cu["key"],
                value=cu["value"],
                chapter_num=chapter_num
            )
            print(f"   [KV写入] 角色 {cu['name']} -> {cu['key']}: {cu['value']}")

        # 2. 写入物品状态更新
        item_updates = memory_updates.get("item_updates", [])
        for iu in item_updates:
            tracker.update_inventory(
                owner=iu["owner"],
                item_name=iu["item_name"],
                action=iu["action"],
                chapter_num=chapter_num
            )
            print(f"   [KV写入] 物品 {iu['item_name']} ({iu['action']}) -> 所属: {iu['owner']}")

        rag_engine = RAGEngine()
        global_events = memory_updates.get("global_events", [])
        if global_events:
            rag_engine.insert_events(global_events, chapter_num)

        print(f"✅ [Memory-Keeper] 第 {chapter_num} 章核心数据持久化完成。上下文窗口压力已释放。")

        try:
            # 采用 001, 002 这种补零格式，保证文件夹内排序正常
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

    except json.JSONDecodeError as e:
        print(f"⚠️ [Memory-Keeper] JSON 解析失败: {e}。本次记忆追踪跳过，但流转继续。")
        return {}
    except Exception as e:
        print(f"⚠️ [Memory-Keeper] 数据库写入异常: {e}")
        return {}