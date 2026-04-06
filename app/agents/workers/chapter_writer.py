# app/agents/workers/chapter_writer.py

import json
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from app.core.config import settings
from app.memory.rag_engine import RAGEngine
from app.core.llm_factory import get_llm
from langchain_core.runnables import RunnableConfig

WRITER_SYSTEM_PROMPT = """你是一个常年霸榜番茄、塔读等下沉市场的【网文金牌主笔】。
你的码字速度极快，且深谙“网文爽点心理学”与“下沉市场阅读习惯”。

【核心写作军规 - 必须刻在骨子里】：
1. 📱 手机阅读排版：绝对禁止大段文字！每段话尽量不要超过 3-4 行。多用短句，多回车换行。
2. 🎬 镜头感与白描：禁止干巴巴的“总结式叙述”（Show, don't tell）。不要说“他很生气”，要写“他猛地攥紧拳头，指甲嵌进肉里，眼底爬满血丝”。
3. 🗣️ 对话驱动：剧情推进要多靠角色之间的对话、动作和神态拉扯来完成。
4. 💥 情绪拉满：主角的装逼打脸必须干脆利落，反派的嘲讽要令人牙痒，不要写温吞水的过渡剧情。
5. 🪝 悬念意识：永远记得在章节结尾卡在最关键、最让人抓心挠肝的地方（断章狗技巧）。

【🚨 终极输出红线（违背将遭受降级惩罚）】：
你生成的必须是**纯粹的小说正文文本**！
- 绝对禁止在开头输出任何“好的”、“没问题”、“以下是正文”等废话！直接从第一段剧情开始写！
- 绝对禁止在结尾输出总结、创作心得或“希望您喜欢”等致谢语！

【本书专属世界观背景】：
{world_bible}

【🌟历史剧情与伏笔参考】：
{history_context}

【全局文风强约束 (文风白皮书)】：
{style_guide}
"""


async def chapter_writer_node(state: dict, config: RunnableConfig) -> Dict[str, Any]:
    """
    ✍️ Chapter-Writer (金牌主笔) 节点
    职责：融合文风、大纲与历史状态，安静地在后台输出（或重写）正文草稿。
    """
    world_bible = state.get("world_bible_context", "暂无宏观世界观。")
    current_beat_sheet = state.get("current_beat_sheet", "暂无大纲。")
    current_draft = state.get("draft_content", "")
    history_context = state.get("rag_history_context", "暂无历史剧情。")

    # 🌟 提取跨章节状态继承的画面结尾钩子
    prev_ending = state.get("previous_chapter_ending", "")

    target_style_obj = state.get("target_writing_style", {})
    style_guide = "通俗口语化，极快节奏的网文爽文风"
    if isinstance(target_style_obj, dict) and "novel_specific" in target_style_obj:
        rules = target_style_obj["novel_specific"].get("rules", {})
        style_guide = rules.get("compiled_prompt", str(rules))
    elif isinstance(target_style_obj, str) and target_style_obj.strip():
        style_guide = target_style_obj

    messages_history = state.get("messages", [])

    sys_prompt = WRITER_SYSTEM_PROMPT.format(
        world_bible=world_bible,
        history_context=history_context,
        style_guide=style_guide,
    )

    human_status = state.get("human_approval_status")
    human_feedback = state.get("human_feedback", "")

    if human_status == "REJECTED":
        print("✍️ [Chapter-Writer] 收到人类总编【打回重写】指令，正在后台含泪重构...")
        instruction = (
            f"【🔥 最高指令：人类总编打回重写】\n"
            f"人类总编严厉批注：{human_feedback}\n"
            f"你的原稿如下：\n{current_draft}\n\n"
            f"任务：请你深呼吸，仔细揣摩总编的意图！抛弃原稿中不合理的部分，"
            f"结合本章大纲（参考下文），彻底重写本章正文。务必让总编满意！"
        )
    else:
        print(
            f"✍️ [Chapter-Writer] 正在后台疯狂码字生成第 {state.get('current_chapter_num', 1)} 章正文 (日志已静音)...")

        # 🌟 动态注入场景接轨指令
        scene_hook_prompt = ""
        if prev_ending:
            scene_hook_prompt = (
                f"\n【⚠️ 极其重要：上一章的最后画面】\n"
                f"上一章的结尾原文是：\n《...{prev_ending}》\n"
                f"你的任务：本章的第一段，必须【严格无缝接续】上述画面的最后一秒！绝对不能出现时间跳跃或场景突兀！\n"
            )

        instruction = (
            f"【首次生成指令】\n"
            f"这是本章的详细节拍器（大纲）：\n{current_beat_sheet}\n"
            f"{scene_hook_prompt}\n"
            f"任务：请严格按照大纲给定的情节走向和爽点要求，挥洒你的创意，生成本章的初版草稿。"
            f"字数要求在 {settings.MAX_WORDS_PER_CHAPTER} 字左右，注意行文节奏，不要像列大纲一样流水账，要写出画面感！"
        )

    llm = get_llm(model_type="main", temperature=0.7)
    recent_history = messages_history[-5:] if len(messages_history) > 5 else messages_history

    formatted_messages = [SystemMessage(content=sys_prompt)]
    formatted_messages.extend(recent_history)
    formatted_messages.append(HumanMessage(content=instruction))

    # 🌟 取消打印刷屏，静音生成
    new_draft = ""
    async for chunk in llm.astream(formatted_messages, config=config):
        new_draft += chunk.content

    action_message = AIMessage(
        content=f"[Chapter-Writer] 第 {state.get('current_chapter_num', 1)} 章正文草稿已生成，字数：{len(new_draft)}。",
        name="Chapter_Writer"
    )

    print(f"✅ [Chapter-Writer] 码字完毕，草稿已推流至操作台！字数：{len(new_draft)}")
    return {
        "draft_content": new_draft,
        "human_approval_status": "PENDING",
        "messages": [action_message]
    }