# app/agents/workers/chapter_writer.py

import json
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from app.core.config import settings
from app.memory.rag_engine import RAGEngine
from app.core.llm_factory import get_llm
from langchain_core.runnables import RunnableConfig
from app.core.context_utils import get_recent_chapters_text

WRITER_SYSTEM_PROMPT = """你是一个常年霸榜番茄、塔读等下沉市场的【网文金牌主笔】。
你的码字速度极快，且深谙“网文爽点心理学”与“下沉市场阅读习惯”。

【📚 最近两章完整原文 (情绪流与上下文强参考)】：
{recent_chapters_text}

【🎬 物理级无缝接续锚点 (绝对红线)】：
{scene_hook_prompt}

【核心写作军规 - 必须刻在骨子里】：
1. 📱 手机阅读排版：绝对禁止大段文字！每段话尽量不要超过 3-4 行。多用短句。
2. 🎬 镜头感与白描：禁止干巴巴的“总结式叙述”（Show, don't tell）。不要说“他很生气”，要写“他猛地攥紧拳头，指甲嵌进肉里，眼底爬满血丝”。
3. 🗣️ 对话驱动：剧情推进要多靠角色之间的对话、动作和神态拉扯来完成。
4. 💥 情绪表现：打脸情节必须干脆利落；如果是日常和结算，则要重点描写围观群众的震惊和主角的深藏不露。
5. 🌊 【拒绝流水账警告（防骨架裸奔）】：你现在拿到的 6-8 个节拍是极度微观的骨架。绝对禁止像写说明书一样把节拍简单串起来！你必须使用大量的“冰山理论”——每个节拍都要用角色的对话拉扯、微表情、环境光影、以及围观者的内心戏来深度包装。如果不水出极高分辨率的画面感，内审编辑会把你打回重写！
6. 💥 每一章的结尾静止像写散文一样总结式收尾是大忌！可以有，但只能出现在【舒缓/日常期】的章节里！其他类型的章节结尾制造强烈的悬念钩子，要么直接卡在生死危机的高潮瞬间！绝对禁止在结尾引入新的危机或伏笔！每章结尾都要让读者欲罢不能，迫不及待想看下一章！
7. 🪝 【本章专属节奏与钩子指令】：
{dynamic_hook_rule}
8. 🛑 【进度物理墙与防溢出红线（绝对红线）】：你必须严格止步于大纲给定的最后一个节拍（Beat）！本章目标字数在 2000 字左右，宁可详细刻画单一场景，也绝对禁止为了凑字数而擅自推进时间线！
9. ⚖️ 【严格执行权重分配】：大纲中每个节拍都标注了字数占比权重（word_count_weight）。对于权重高的节拍，必须当成“核心大轴戏”多加对白心理；对于权重低的节拍，干脆利落一笔带过！
10. 🛑 【绝对禁止前情提要 / 防复读警告】：我为你提供了《最近两章完整原文》，仅仅是为了让你把握住对话惯性、情绪流和前置语境！你敲下的第一行字必须紧跟上方的【物理级无缝接续锚点】！绝对禁止出现“话说上回”、“在上一章中”、“之前发生了什么”等任何回忆性的废话！

【🚨 终极输出红线（违背将遭受降级惩罚）】：
你生成的必须是**纯粹的小说正文文本**！绝对禁止在正文中使用“一、”“1.”等小标题分段！绝对禁止输出“好的”、“以下是正文”等废话！

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
    # === 1. 从状态机提取基础参数 ===
    world_bible = state.get("world_bible_context", "暂无宏观世界观。")
    current_beat_sheet = state.get("current_beat_sheet", "暂无大纲。")
    current_draft = state.get("draft_content", "")
    history_context = state.get("rag_history_context", "暂无历史剧情。")
    current_chapter_num = state.get("current_chapter_num", 1)
    prev_ending = state.get("previous_chapter_ending", "")
    messages_history = state.get("messages", [])
    current_book_id = state.get("book_id", "default_book")

    # === 2. 动态确定文风 ===
    target_style_obj = state.get("target_writing_style", {})
    style_guide = "通俗口语化，极快节奏的网文爽文风"
    if isinstance(target_style_obj, dict) and "novel_specific" in target_style_obj:
        rules = target_style_obj["novel_specific"].get("rules", {})
        style_guide = rules.get("compiled_prompt", str(rules))
    elif isinstance(target_style_obj, str) and target_style_obj.strip():
        style_guide = target_style_obj

    # === 3. 动态确定结尾悬念钩子 ===
    idx = (current_chapter_num - 1) % 10
    if idx in [0, 1, 2]:
        dynamic_hook_rule = "本章是【舒缓/日常期】。结尾绝不要制造生死危机，请用温馨、期待、或发现小秘密的画面作为自然收尾。"
    elif idx in [3, 4, 5]:
        dynamic_hook_rule = "本章是【蓄力/探索期】。结尾请抛出一个悬疑感极强的钩子，比如推开一扇门、某人一句意味深长的话，引导读者期待下一章。"
    elif idx in [6, 7, 8]:
        dynamic_hook_rule = "本章是【爆发/高潮期】。使用断章狗技巧！章节结尾必须卡在最关键、最抓心挠肝的生死瞬间，或反派即将亮出杀招的一刻！"
    else:
        dynamic_hook_rule = "本章是【结算/余波期】。高潮已过，【绝对禁止】在结尾引出新的危机！结尾应该是战利品清点后的满足，或对下一段旅程的从容眺望。"

    # === 4. 获取前两章原文 ===
    recent_chapters_text = get_recent_chapters_text(current_book_id, current_chapter_num, n=2)

    # === 5. 组装 500 字无缝接续锚点 ===
    if prev_ending:
        scene_hook_prompt = (
            f"上一章的最后500字原文是：\n《...{prev_ending}》\n"
            f"任务：本章的第一段，必须【严丝合缝】地接续上述画面的最后一个动作或最后一句话！"
            f"绝对禁止出现任何时间跳跃或场景突兀！直接顺着上文往下写！"
        )
    else:
        scene_hook_prompt = "（全书或新卷首章，暂无上一章结尾锚点，请直接从本章节拍一开始正常开局）"

    # === 6. 注入系统级 Prompt ===
    sys_prompt = WRITER_SYSTEM_PROMPT.format(
        recent_chapters_text=recent_chapters_text,
        scene_hook_prompt=scene_hook_prompt,
        world_bible=world_bible,
        history_context=history_context,
        style_guide=style_guide,
        dynamic_hook_rule=dynamic_hook_rule
    )

    # === 7. 根据流转状态，决定具体生成指令 ===
    human_status = state.get("human_approval_status")
    human_feedback = state.get("human_feedback", "")
    editor_comments = state.get("editor_comments", "")

    if human_status == "REJECTED":
        print("✍️ [Chapter-Writer] 收到人类总编【打回重写】指令，正在后台含泪重构...")
        instruction = (
            f"【🔥 最高指令：人类总编打回重写】\n"
            f"人类总编严厉批注：{human_feedback}\n"
            f"你的原稿如下：\n{current_draft}\n\n"
            f"任务：请你深呼吸，仔细揣摩总编的意图！抛弃原稿中不合理的部分，"
            f"结合本章大纲（参考下文），彻底重写本章正文。务必让总编满意！"
        )
    elif editor_comments == "FAIL":
        # 从消息总线中捞取刚刚 Editor 发出的批评意见
        last_editor_msg = ""
        for msg in reversed(messages_history):
            if getattr(msg, "name", "") == "Continuity_Editor":
                last_editor_msg = msg.content
                break

        print(f"✍️ [Chapter-Writer] 收到内审打回指令，正在疯狂填补细节注水...")
        instruction = (
            f"【⚠️ 内部质检打回重写】\n"
            f"主笔，你的上一版草稿未能通过系统内审！要么字数太少，要么抢跑越界了！\n"
            f"以下是主编(内审组)的打回意见：\n{last_editor_msg}\n\n"
            f"你的上一版原稿字数为 {len(current_draft)} 字，原稿如下：\n{current_draft}\n\n"
            f"任务：仔细阅读内审意见！绝对禁止往后推时间线抢跑！如果字数不够，请在节拍器要求的高权重画面疯狂加环境白描、围观者惊叹、人物心理拉扯注水！彻底重写本章正文。"
        )
    else:
        print(f"✍️ [Chapter-Writer] 正在后台疯狂码字生成第 {current_chapter_num} 章正文 (日志已静音)...")
        instruction = (
            f"【首次生成指令】\n"
            f"这是本章的详细节拍器（大纲）。⚠️注意：请将大纲情节融合成连贯自然的连续小说正文，绝对禁止在正文里照抄大纲的标号或保留大纲的痕迹！\n{current_beat_sheet}\n"
            f"任务：请严格按照大纲给定的情节走向和爽点要求，挥洒你的创意，生成本章的初版草稿。"
            f"字数要求在 {settings.MAX_WORDS_PER_CHAPTER} 字左右，宁可详细刻画单一场景，也绝对禁止为了凑字数推进时间线！严格遵循大纲每个节拍的 word_count_weight 权重，不要像列大纲一样流水账，要写出极高分辨率的画面感！"
        )

    # === 8. 组装历史消息并调用大模型 ===
    # 💡 提示：作为主力创作节点，建议 model_type 保持为 "main" (如 DeepSeek, GPT-4o 等) 以确保文笔质量。
    llm = get_llm(model_type="main", temperature=0.7)
    recent_history = messages_history[-5:] if len(messages_history) > 5 else messages_history

    formatted_messages = [SystemMessage(content=sys_prompt)]
    formatted_messages.extend(recent_history)
    formatted_messages.append(HumanMessage(content=instruction))

    # 流式生成与收集
    new_draft = ""
    async for chunk in llm.astream(formatted_messages, config=config):
        new_draft += chunk.content

    action_message = AIMessage(
        content=f"[Chapter-Writer] 第 {current_chapter_num} 章正文草稿已生成，字数：{len(new_draft)}。",
        name="Chapter_Writer"
    )

    print(f"✅ [Chapter-Writer] 码字完毕，草稿已推流至操作台！字数：{len(new_draft)}")
    return {
        "draft_content": new_draft,
        "human_approval_status": "PENDING",
        "messages": [action_message]
    }