# app/agents/workers/chapter_writer.py
import os
import json
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from app.core.config import settings
from app.memory.rag_engine import RAGEngine
from app.core.llm_factory import get_llm
from langchain_core.runnables import RunnableConfig

WRITER_SYSTEM_PROMPT = """你是一个常年霸榜番茄、塔读等下沉市场的【网文金牌主笔】。
你的码字速度极快，且深谙“网文爽点心理学”与“下沉市场阅读习惯”。

【📚 前情提要 (短期记忆与上下文强参考)】：
{recent_chapter_summary}

【🎬 物理级无缝接续锚点 (绝对红线)】：
{scene_hook_prompt}

【核心写作军规 - 必须刻在骨子里】：
1. 📱 手机阅读排版：绝对禁止大段文字！每段话尽量不要超过 3-4 行。多用短句。
2. 🎬 镜头感与白描：禁止干巴巴的“总结式叙述”（Show, don't tell）。不要说“他很生气”，要写“他猛地攥紧拳头，指甲嵌进肉里，眼底爬满血丝”。
3. 🗣️ 对话驱动：剧情推进要多靠角色之间的对话、动作和神态拉扯来完成。
4. 💥 情绪表现：打脸情节必须干脆利落；如果是日常和结算，则要重点描写围观群众的震惊和主角的深藏不露。
5. 🌊 【拒绝流水账警告（防骨架裸奔）】：你现在拿到的节拍是极度微观的骨架。绝对禁止像写说明书一样把节拍简单串起来！你必须使用大量的“冰山理论”——每个节拍都要用角色的对话拉扯、微表情、环境光影、以及围观者的内心戏来深度包装。
6. 💥 每一章的结尾静止像写散文一样总结式收尾是大忌！可以有，但只能出现在【舒缓/日常期】的章节里！其他类型的章节结尾制造强烈的悬念钩子，要么直接卡在生死危机的高潮瞬间！
7. 🪝 【本章专属节奏与钩子指令】：
{dynamic_hook_rule}
8. 🛑 【进度物理墙与防溢出红线（绝对红线）】：你必须严格止步于大纲给定的最后一个节拍（Beat）！宁可详细刻画单一场景，也绝对禁止为了凑字数而擅自推进时间线！
9. ⚖️ 【严格执行权重分配】：大纲中每个节拍都标注了字数占比权重。对于权重高的节拍，必须当成“核心大轴戏”多加对白心理；对于权重低的节拍，干脆利落一笔带过！
10. 🛑 【绝对禁止前情提要 / 防复读警告】：我为你提供了《前情提要》，仅仅是为了让你把握住对话惯性、情绪流和前置语境！你敲下的第一行字必须紧跟上方的【物理级无缝接续锚点】！绝对禁止出现“话说上回”、“在上一章中”等任何回忆性的废话！

【🚨 终极输出红线（违背将遭受降级惩罚）】：
你生成的必须是**纯粹的小说正文文本**！绝对禁止在正文中使用“一、”“1.”等小标题分段！绝对禁止输出“好的”、“以下是正文”等废话！

【本书专属世界观背景】：
{world_bible}

【🌟历史剧情与伏笔参考】：
{history_context}

【全局文风强约束 (文风白皮书)】：
{style_guide}

【🔥 黄金范文 (请深度模仿以下行文节奏与白描手法)】：
{examples_str}
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

    # 🌟 获取上文摘要
    recent_chapter_summary = state.get("recent_chapter_summary", "（暂无前情提要）")

    # === 2. 动态确定文风与提取黄金范文 ===
    target_style_obj = state.get("target_writing_style", {})
    style_guide = "通俗口语化，极快节奏的网文爽文风"
    examples_str = "（暂无具体范文，请依靠系统指令发挥）"

    if isinstance(target_style_obj, dict) and "novel_specific" in target_style_obj:
        rules = target_style_obj["novel_specific"].get("rules", {})
        style_guide = rules.get("compiled_prompt", str(rules))
        # 提取 Few-shot 范文
        examples = rules.get("example_snippets", [])
        if isinstance(examples, list) and examples:
            examples_str = "\n".join([f"示例片段 {i + 1}:\n{ex}" for i, ex in enumerate(examples)])
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

    # === 4. 组装 500 字无缝接续锚点 ===
    if prev_ending:
        scene_hook_prompt = (
            f"上一章的最后500字原文是：\n《...{prev_ending}》\n"
            f"任务：本章的第一段，必须【严丝合缝】地接续上述画面的最后一个动作或最后一句话！"
            f"绝对禁止出现任何时间跳跃或场景突兀！直接顺着上文往下写！"
        )
    else:
        scene_hook_prompt = "（全书或新卷首章，暂无上一章结尾锚点，请直接从本章节拍一开始正常开局）"

    # === 5. 注入系统级 Prompt ===
    sys_prompt = WRITER_SYSTEM_PROMPT.format(
        recent_chapter_summary=recent_chapter_summary,
        scene_hook_prompt=scene_hook_prompt,
        world_bible=world_bible,
        history_context=history_context,
        style_guide=style_guide,
        examples_str=examples_str,
        dynamic_hook_rule=dynamic_hook_rule
    )

    # === 6. 获取流转状态与历史记录 ===
    human_status = state.get("human_approval_status")
    human_feedback = state.get("human_feedback", "")
    editor_comments = state.get("editor_comments", "")

    llm = get_llm(model_type="main", temperature=0.7)
    recent_history = messages_history[-5:] if len(messages_history) > 5 else messages_history
    is_rewrite = (human_status == "REJECTED" or editor_comments == "FAIL")

    new_draft = ""

    # === 7. 核心分支：单次重写 vs 分段(Chunked)首次生成 ===
    if is_rewrite:
        if human_status == "REJECTED":
            print("✍️ [Chapter-Writer] 收到人类总编【打回重写】指令，正在后台含泪重构...")
            instruction = (
                f"【🔥 最高指令：人类总编打回重写】\n"
                f"人类总编严厉批注：{human_feedback}\n"
                f"你的原稿如下：\n{current_draft}\n\n"
                f"任务：请仔细揣摩总编意图，抛弃原稿不合理部分，结合大纲彻底重写本章正文。务必让总编满意！"
            )
        else:
            last_editor_msg = ""
            for msg in reversed(messages_history):
                if getattr(msg, "name", "") == "Continuity_Editor":
                    last_editor_msg = msg.content
                    break
            print(f"✍️ [Chapter-Writer] 收到内审打回指令，正在疯狂填补细节注水...")
            instruction = (
                f"【⚠️ 内部质检打回重写】\n"
                f"以下是主编(内审组)的打回意见：\n{last_editor_msg}\n\n"
                f"你的原稿如下：\n{current_draft}\n\n"
                f"任务：仔细阅读内审意见！绝对禁止往后推时间线抢跑！如果字数不够，请在节拍器要求的高权重画面疯狂加环境白描与心理戏！彻底重写。"
            )

        formatted_messages = [SystemMessage(content=sys_prompt)] + recent_history + [HumanMessage(content=instruction)]
        async for chunk in llm.astream(formatted_messages, config=config):
            new_draft += chunk.content

    else:
        # 🌟 首次生成采用分段生成 (Chunked Generation)
        print(f"✍️ [Chapter-Writer] 正在执行分段式码字生成第 {current_chapter_num} 章正文...")
        try:
            beat_sheet_dict = json.loads(current_beat_sheet)
            beats = beat_sheet_dict.get("beats", [])
        except:
            beats = []

        if len(beats) >= 2:
            mid_index = len(beats) // 2 + len(beats) % 2
            part1_beats = beats[:mid_index]
            part2_beats = beats[mid_index:]

            part1_outline = json.dumps({"beats": part1_beats}, ensure_ascii=False, indent=2)
            part2_outline = json.dumps({"beats": part2_beats}, ensure_ascii=False, indent=2)

            # --- 第 1 次调用：生成上半篇 ---
            print("   [Chunk 1] 正在生成上半篇...")
            instr_part1 = (
                f"【上半篇首次生成指令】\n"
                f"这是本章的前半部分详细节拍器（大纲）：\n{part1_outline}\n"
                f"任务：请严格按照这部分大纲，生成上半篇的正文。目标字数 1500 字左右。\n"
                f"🚨 绝对红线：严禁越界写出大纲未提及的后续剧情！多运用冰山理论写细节！"
            )
            messages_p1 = [SystemMessage(content=sys_prompt)] + recent_history + [HumanMessage(content=instr_part1)]

            part1_draft = ""
            async for chunk in llm.astream(messages_p1, config=config):
                part1_draft += chunk.content
                # ❌ 已删除这里的 yield chunk，依赖 LangChain 回调自动推流

            # --- 第 2 次调用：生成下半篇 ---
            print("   [Chunk 2] 正在生成下半篇...")
            instr_part2 = (
                f"【下半篇首次生成指令】\n"
                f"这是本章的后半部分详细节拍器（大纲）：\n{part2_outline}\n"
                f"【重要：你的上半篇前文参考 (请顺着语气接着写)】：\n{part1_draft}\n"
                f"任务：紧接上半篇的情绪和动作，完成下半篇的正文。目标字数 1500 字左右。\n"
                f"🚨 绝对红线：严禁重复上半篇已经写过的剧情！严厉执行结尾钩子规则！"
            )
            messages_p2 = [SystemMessage(content=sys_prompt)] + recent_history + [HumanMessage(content=instr_part2)]

            part2_draft = "\n\n"
            async for chunk in llm.astream(messages_p2, config=config):
                part2_draft += chunk.content
                # ❌ 已删除这里的 yield chunk，依赖 LangChain 回调自动推流

            new_draft = part1_draft + part2_draft

        else:
            # 兜底：如果节拍太少或解析失败，单次生成
            instruction = (
                f"【首次生成指令】\n"
                f"这是本章的大纲：\n{current_beat_sheet}\n"
                f"任务：请严格按照大纲给定的情节走向和爽点要求生成初稿，目标 2000 字左右。"
            )
            formatted_messages = [SystemMessage(content=sys_prompt)] + recent_history + [
                HumanMessage(content=instruction)]
            async for chunk in llm.astream(formatted_messages, config=config):
                new_draft += chunk.content

    # === 8. 保存与返回 ===
    action_message = AIMessage(
        content=f"[Chapter-Writer] 第 {current_chapter_num} 章正文草稿已生成，字数：{len(new_draft)}。",
        name="Chapter_Writer"
    )

    print(f"✅ [Chapter-Writer] 码字完毕，总字数：{len(new_draft)}")
    draft_path = os.path.join(settings.DATA_DIR, current_book_id, f"temp_draft_{current_chapter_num}.txt")
    with open(draft_path, "w", encoding="utf-8") as f:
        f.write(new_draft)

    # ✅ 节点正常返回字典状态
    return {
        "draft_path": draft_path,
        "human_approval_status": "PENDING",
        "messages": [action_message]
    }