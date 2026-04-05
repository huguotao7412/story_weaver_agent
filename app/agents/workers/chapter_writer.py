#职责：苦力担当。融合《文风白皮书》与单章大纲，输出白话、明快、极具网文感的正文草稿。
# app/agents/workers/chapter_writer.py

import json
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage,AIMessage
from app.core.config import settings
from app.memory.rag_engine import RAGEngine

# 引入 LLM 工厂
from app.core.llm_factory import get_llm

# ==========================================
# ✍️ 金牌主笔：核心基础提示词 (系统级约束)
# ==========================================
WRITER_SYSTEM_PROMPT = """你是一个常年霸榜番茄、塔读等下沉市场的【网文金牌主笔】。
你的码字速度极快，且深谙“网文爽点心理学”与“下沉市场阅读习惯”。

【核心写作军规 - 必须刻在骨子里】：
1. 📱 手机阅读排版：绝对禁止大段文字！每段话尽量不要超过 3-4 行。多用短句，多回车换行。
2. 🎬 镜头感与白描：禁止干巴巴的“总结式叙述”（Show, don't tell）。不要说“他很生气”，要写“他猛地攥紧拳头，指甲嵌进肉里，眼底爬满血丝”。
3. 🗣️ 对话驱动：剧情推进要多靠角色之间的对话、动作和神态拉扯来完成。
4. 💥 情绪拉满：主角的装逼打脸必须干脆利落，反派的嘲讽要令人牙痒，不要写温吞水的过渡剧情。
5. 🪝 悬念意识：永远记得在章节结尾卡在最关键、最让人抓心挠肝的地方（断章狗技巧）。

【本书专属世界观背景】：
{world_bible}

【🌟历史剧情与伏笔参考】：
{history_context}

【全局文风强约束 (文风白皮书)】：
{style_guide}
"""


async def chapter_writer_node(state: dict) -> Dict[str, Any]:
    """
    ✍️ Chapter-Writer (金牌主笔) 节点
    职责：融合文风、大纲与历史状态，输出（或重写）正文草稿。
    """
    # 1. 从图状态中提取所需上下文
    world_bible = state.get("world_bible_context", "暂无宏观世界观。")
    current_beat_sheet = state.get("current_beat_sheet", "暂无大纲。")
    current_draft = state.get("draft_content", "")

    history_context = state.get("rag_history_context", "暂无历史剧情。")

    # 提取文风白皮书 (处理 SharedValue 格式或普通格式)
    target_style_obj = state.get("target_writing_style", {})
    style_guide = "通俗口语化，极快节奏的网文爽文风"  # 默认兜底
    if isinstance(target_style_obj, dict) and "novel_specific" in target_style_obj:
        rules = target_style_obj["novel_specific"].get("rules", {})
        style_guide = rules.get("compiled_prompt", str(rules))
    elif isinstance(target_style_obj, str) and target_style_obj.strip():
        style_guide = target_style_obj

    messages_history = state.get("messages", [])

    # 2. 组装系统级 Prompt
    sys_prompt = WRITER_SYSTEM_PROMPT.format(
        world_bible=world_bible,
        history_context=history_context,
        style_guide=style_guide,
    )

    # 3. 🌟 根据事务流转状态，动态生成“指令 (Instruction)”
    # 完美贯彻白皮书中的“看人下菜碟”逻辑
    human_status = state.get("human_approval_status")
    editor_comments = state.get("editor_comments")
    human_feedback = state.get("human_feedback", "")

    if human_status == "REJECTED":
        print("✍️ [Chapter-Writer] 收到人类总编【最高优先级指令】，正在含泪重写...")
        instruction = (
            f"【🔥 最高指令：人类总编打回重写】\n"
            f"人类总编严厉批注：{human_feedback}\n"
            f"你的原稿如下：\n{current_draft}\n\n"
            f"任务：请你深呼吸，仔细揣摩总编的意图！抛弃原稿中不合理的部分，"
            f"结合本章大纲（参考下文），彻底重写本章正文。务必让总编满意！"
        )
    elif editor_comments and editor_comments != "PASS":
        print("✍️ [Chapter-Writer] 收到内部逻辑审查员的返工要求，正在修补 Bug...")
        instruction = (
            f"【内部 AI 审查返工指令】\n"
            f"逻辑审查员在你的草稿中发现了致命漏洞或设定冲突：\n{editor_comments}\n"
            f"你的原稿如下：\n{current_draft}\n\n"
            f"任务：网文虽然是爽文，但绝不能前后矛盾。请仔细阅读大纲，修复上述 Bug，重新输出逻辑严丝合缝的正文草稿。"
        )
    else:
        print("✍️ [Chapter-Writer] 拿到全新大纲，正在文思泉涌，奋笔疾书首次草稿...")
        instruction = (
            f"【首次生成指令】\n"
            f"这是本章的详细节拍器（大纲）：\n{current_beat_sheet}\n\n"
            f"任务：请严格按照大纲给定的情节走向和爽点要求，挥洒你的创意，生成本章的初版草稿。"
            f"字数要求在 {settings.MAX_WORDS_PER_CHAPTER} 字左右，注意行文节奏，不要像列大纲一样流水账，要写出画面感！"
        )

    # 4. 调用 LLM (主笔需要强大的文本生成能力和一定的温度值以保证创造力)
    # 这里推荐温度稍微高一点 (e.g., 0.7)，让文字更有网文的张力
    llm = get_llm(model_type="main", temperature=0.7)

    recent_history = messages_history[-5:] if len(messages_history) > 5 else messages_history

    formatted_messages = [
        SystemMessage(content=sys_prompt)
    ]
    formatted_messages.extend(recent_history)
    formatted_messages.append(HumanMessage(content=instruction))

    response =await llm.ainvoke(formatted_messages)
    new_draft = response.content.strip()

    action_message = AIMessage(
        content=f"[Chapter-Writer] 第 {state.get('current_chapter_num', 1)} 章正文草稿已生成，字数：{len(new_draft)}。",
        name="Chapter_Writer"
    )

    # 5. 更新状态区的草稿内容 (此时绝对不能入库，只留在隔离草稿区)
    # 同时，每次生成新的草稿后，清理掉之前的审查意见，准备迎接下一轮审查
    return {
        "draft_content": new_draft,
        "editor_comments": "",  # 重置内部审查状态
        "human_approval_status": "PENDING" , # 重置人类审查状态为待定
        "messages": [action_message]
    }