# app/agents/workers/continuity_editor.py
import os
import json
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from app.memory.kv_tracker import AsyncKVTracker
from app.core.llm_factory import get_llm
from protocols.hitl_schemas import EditorInternalReview

EDITOR_SYSTEM_PROMPT = """你是一个冷酷无情的网文【内部质检编辑】 (Continuity Editor)。
主笔刚刚生成了本章的正文草稿。你的唯一任务是核对草稿是否严格遵守了节拍器（大纲）与创作底线！
【当前人物与设定权威快照】：
{kv_state}

【你的五大质检红线（触发任意一条直接判定 FAIL）】：
1. 🛑 时间线越界核对（最致命）：严格对比【草稿的最后一个动作】与【节拍器的最后一个节点】。如果草稿超出了大纲给定的最后一个节拍（即：抢跑写了后面的剧情），直接判定 FAIL！并指出越界的情节。
2. 📉 字数底线核对：本章目标是 2000 字左右。当前草稿字数为 {draft_len} 字。如果低于 1600 字，必须判定 FAIL，并在 revision_suggestions 中严厉命令主笔：“不许往后推剧情！必须在核心高权重节拍上增加对话、白描和心理活动！”
3. 🪝 结尾钩子核对：检查草稿最后一段是否符合本章所处心流期的结尾钩子要求。如果本该是悬念结尾却写成了总结式散文，判定 FAIL。
4.✂️ 【局部截断法指令】：如果仅仅是结尾处抢跑，你的 `revision_suggestions` 绝对不要让主笔全部重写！应当给出类似这样的精确指令：“前 1700 字保留，请把最后 300 字进城的剧情全部删去，替换成看着城门沉思的背影作为悬念收尾。”
5. 🛡️ 事实与战力核对 (OOC 红线)：仔细比对草稿内容与上方的【权威快照】。
   - 如果草稿中出现了快照中已标记为“死亡”的角色复活。
   - 如果角色的境界/等级发生了没有过程的突变（例如快照是练气，草稿直接写成元婴）。
   发现以上任意一条，必须判定 FAIL，并在 bug_reports 中精准指出 OOC 漏洞！
注意：你只做裁判，不亲自修改正文。必须以结构化 JSON 格式输出质检结果。
"""

async def continuity_editor_node(state: dict) -> Dict[str, Any]:
    tracker = AsyncKVTracker(book_id=state.get("book_id"))
    await tracker.init_db()
    current_kv_state = await tracker.get_world_bible_snapshot()
    draft_path = state.get("draft_path", "")
    draft = ""
    if draft_path and os.path.exists(draft_path):
        with open(draft_path, "r", encoding="utf-8") as f:
            draft = f.read()
    beat_sheet = state.get("current_beat_sheet", "")
    revision_count = state.get("internal_revision_count", 0)
    chapter_num = state.get("current_chapter_num", 1)

    if not draft:
        return {"editor_comments": "PASS"}

    print(f"🕵️ [Continuity-Editor] 正在对第 {chapter_num} 章草稿进行严格内审... (当前重试: {revision_count}/2)")

    # 🌟 双重防爆机制：超过 2 次直接放行，避免大模型死循环消耗 Token
    if revision_count >= 2:
        print("⚠️ [Continuity-Editor] 连续打回次数已达上限 (2次)，强制放行交由人类总编裁决。")
        return {
            "editor_comments": "PASS_WITH_WARNING",
            "internal_revision_count": 0
        }

    llm = get_llm(model_type="main", temperature=0.1) # 质检节点温度调低，确保理性
    structured_llm = llm.with_structured_output(EditorInternalReview, method="function_calling")

    prompt = EDITOR_SYSTEM_PROMPT.format(draft_len=len(draft))
    human_content = f"【本章规定节拍器 (绝对红线)】：\n{beat_sheet}\n\n【主笔生成的正文草稿】：\n{draft}\n\n请进行严格质检。"

    try:
        review: EditorInternalReview = await structured_llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=human_content)
        ])

        if review.status == "FAIL":
            print(f"❌ [Continuity-Editor] 质检未通过！发现问题：{review.bug_reports}")
            feedback_msg = AIMessage(
                content=f"【内部质检打回】\n扣分点: {review.bug_reports}\n修改建议: {review.revision_suggestions}",
                name="Continuity_Editor"
            )
            return {
                "editor_comments": "FAIL",
                "internal_revision_count": revision_count + 1,
                "messages": [feedback_msg]
            }
        else:
            print("✅ [Continuity-Editor] 质检完美通过！无越界与字数问题。")
            return {
                "editor_comments": "PASS",
                "internal_revision_count": 0
            }

    except Exception as e:
        print(f"⚠️ [Continuity-Editor] 质检发生异常，默认放行: {e}")
        return {"editor_comments": "PASS", "internal_revision_count": 0}