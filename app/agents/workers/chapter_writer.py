# app/agents/workers/chapter_writer.py
import os
import json
import re
from typing import Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agents.base import BaseAgent
from app.core.config import settings
from app.core.llm_factory import get_llm
from app.agents.registry import register


class ChapterWriterAgent(BaseAgent):
    name = "Chapter_Writer"
    prompt_file = "chapter_writer.yaml"

    async def execute(self, state: dict, config: RunnableConfig = None) -> Dict[str, Any]:
        world_bible = state.get("world_bible_context", "暂无宏观世界观。")
        current_beat_sheet = state.get("current_beat_sheet", "暂无大纲。")
        history_context = state.get("rag_history_context", "暂无历史剧情。")
        current_chapter_num = state.get("current_chapter_num", 1)
        prev_ending = state.get("previous_chapter_ending", "")
        current_book_id = state.get("book_id", "default_book")

        draft_path = state.get("draft_path", "")
        current_draft = ""
        if draft_path and os.path.exists(draft_path):
            with open(draft_path, "r", encoding="utf-8") as f:
                current_draft = f.read()

        revision_history = state.get("revision_history", [])
        history_text = "\n".join(revision_history) if revision_history else "无打回记录"

        summary_list = state.get("recent_chapters_summary", [])
        recent_chapters_summary = "\n\n".join([f"【N-{len(summary_list) - i} 前情脉络】:\n{text}" for i, text in
                                               enumerate(summary_list)]) if summary_list else "（暂无前情提要）"

        target_style_obj = state.get("target_writing_style", {})
        style_guide = "通俗口语化，极快节奏的网文爽文风"
        examples_str = "（暂无具体范文，请依靠系统指令发挥）"

        if isinstance(target_style_obj, dict) and "novel_specific" in target_style_obj:
            rules = target_style_obj["novel_specific"].get("rules", {})
            style_guide = rules.get("compiled_prompt", str(rules))
            examples = rules.get("example_snippets", [])
            if isinstance(examples, list) and examples:
                examples_str = "\n".join([f"示例片段 {i + 1}:\n{ex}" for i, ex in enumerate(examples)])
        elif isinstance(target_style_obj, str) and target_style_obj.strip():
            style_guide = target_style_obj

        idx = (current_chapter_num - 1) % 10
        if idx in [0, 1, 2]:
            dynamic_hook_rule = "本章是【舒缓/日常期】。结尾绝不要制造生死危机，请用温馨、期待、或发现小秘密的画面作为自然收尾。"
        elif idx in [3, 4, 5]:
            dynamic_hook_rule = "本章是【蓄力/探索期】。结尾请抛出一个悬疑感极强的钩子，比如推开一扇门、某人一句意味深长的话，引导读者期待下一章。"
        elif idx in [6, 7, 8]:
            dynamic_hook_rule = "本章是【爆发/高潮期】。使用断章狗技巧！章节结尾必须卡在最关键、最抓心挠肝的生死瞬间，或反派即将亮出杀招的一刻！"
        else:
            dynamic_hook_rule = "本章是【结算/余波期】。高潮已过，【绝对禁止】在结尾引出新的危机！结尾应该是战利品清点后的满足，或对下一段旅程的从容眺望。"

        if prev_ending:
            scene_hook_prompt = (
                f"上一章的最后500字原文是：\n《...{prev_ending}》\n"
                f"任务：本章的第一段，必须【严丝合缝】地接续上述画面的最后一个动作或最后一句话！"
                f"绝对禁止出现任何时间跳跃或场景突兀！直接顺着上文往下写！"
            )
        else:
            scene_hook_prompt = "（全书或新卷首章，暂无上一章结尾锚点，请直接从本章节拍一开始正常开局）"

        human_status = state.get("human_approval_status")
        human_feedback = state.get("human_feedback", "")
        editor_comments = state.get("editor_comments", "")

        llm = get_llm(temperature=0.7)

        is_rewrite = (human_status == "REJECTED" or editor_comments == "FAIL")

        new_draft = ""

        if is_rewrite:
            sys_prompt = self.load_prompt(
                recent_chapters_summary=recent_chapters_summary,
                scene_hook_prompt=scene_hook_prompt,
                world_bible=world_bible,
                history_context=history_context,
                style_guide=style_guide,
                examples_str=examples_str,
                dynamic_hook_rule=dynamic_hook_rule
            )[0].content

            if human_status == "REJECTED":
                print("✍️ [Chapter-Writer] 收到人类总编【打回重写】指令，正在后台含泪重构...")
                instruction = (
                    f"【🔥 最高指令：人类总编打回重写】\n"
                    f"人类总编严厉批注：{human_feedback}\n"
                    f"以下是本章经历的历史打回记录与建议（请避开同样的错误）：\n{history_text}\n\n"
                    f"你的原稿如下：\n{current_draft}\n\n"
                    f"任务：请仔细揣摩总编意图，抛弃原稿不合理部分，结合大纲彻底重写本章正文。务必让总编满意！"
                )
            else:
                print(f"✍️ [Chapter-Writer] 收到内审打回指令，正在疯狂填补细节注水...")
                instruction = (
                    f"【⚠️ 内部质检打回重写】\n"
                    f"以下是主编(内审组)的打回意见栈：\n{history_text}\n\n"
                    f"你的原稿如下：\n{current_draft}\n\n"
                    f"任务：仔细阅读内审意见！绝对禁止往后推时间线抢跑！如果字数不够，请在节拍器要求的高权重画面疯狂加环境白描与心理戏！彻底重写。"
                )

            formatted_messages = [SystemMessage(content=sys_prompt), HumanMessage(content=instruction)]
            if config:
                async for chunk in llm.astream(formatted_messages, config=config):
                    new_draft += chunk.content
            else:
                response = await llm.ainvoke(formatted_messages)
                new_draft = response.content

        else:
            print(f"✍️ [Chapter-Writer] 正在执行分段式码字生成第 {current_chapter_num} 章正文...")
            try:
                cleaned_sheet = re.sub(r"^```json\s*", "", current_beat_sheet).replace("```", "").strip()
                parsed_data = json.loads(cleaned_sheet)
                if isinstance(parsed_data, dict) and "beats" in parsed_data:
                    beats = parsed_data["beats"]
                elif isinstance(parsed_data, list):
                    beats = parsed_data
                else:
                    beats = []
            except Exception as e:
                print(f"⚠️ [Chapter-Writer] 大纲 JSON 反序列化失败: {e}", flush=True)
                beats = []

            if len(beats) >= 2:
                mid_index = len(beats) // 2 + len(beats) % 2
                part1_beats = beats[:mid_index]
                part2_beats = beats[mid_index:]

                part1_outline = json.dumps({"beats": part1_beats}, ensure_ascii=False, indent=2)
                part2_outline = json.dumps({"beats": part2_beats}, ensure_ascii=False, indent=2)

                def calc_target_words(beats_list, total_words=settings.MAX_WORDS_PER_CHAPTER):
                    try:
                        weight_sum = sum(
                            [float(str(b.get("word_count_weight", "0")).replace("%", "")) for b in beats_list])
                        return max(int((weight_sum / 100) * total_words), 500)
                    except:
                        return 1500

                target_words_p1 = calc_target_words(part1_beats)
                target_words_p2 = calc_target_words(part2_beats)

                sys_prompt_text = self.load_prompt(
                    recent_chapters_summary=recent_chapters_summary,
                    scene_hook_prompt=scene_hook_prompt,
                    world_bible=world_bible,
                    history_context=history_context,
                    style_guide=style_guide,
                    examples_str=examples_str,
                    dynamic_hook_rule=dynamic_hook_rule
                )[0].content

                print(f"   [Chunk 1] 正在生成上半篇 (目标字数: ~{target_words_p1}字)...")
                instr_part1 = (
                    f"【上半篇首次生成指令】\n"
                    f"这是本章的前半部分详细节拍器（大纲）：\n{part1_outline}\n"
                    f"任务：请严格按照这部分大纲，生成上半篇的正文。目标字数 {target_words_p1} 字左右。\n"
                    f"🚨 绝对红线：严禁越界写出大纲未提及的后续剧情！多运用冰山理论写细节！"
                )
                messages_p1 = [SystemMessage(content=sys_prompt_text), HumanMessage(content=instr_part1)]

                part1_draft = ""
                if config:
                    async for chunk in llm.astream(messages_p1, config=config):
                        part1_draft += chunk.content
                else:
                    response = await llm.ainvoke(messages_p1)
                    part1_draft = response.content

                print(f"   [Chunk 2] 正在生成下半篇 (目标字数: ~{target_words_p2}字)...")
                sys_prompt_part2 = self.load_prompt(
                    recent_chapters_summary=recent_chapters_summary,
                    scene_hook_prompt="（这是本章的下半篇，请直接紧接上方【上半篇前文参考】的最后一个动作继续写，绝不要另起炉灶！）",
                    world_bible=world_bible,
                    history_context=history_context,
                    style_guide=style_guide,
                    examples_str=examples_str,
                    dynamic_hook_rule=dynamic_hook_rule
                )[0].content
                instr_part2 = (
                    f"【下半篇首次生成指令】\n"
                    f"这是本章的后半部分详细节拍器（大纲）：\n{part2_outline}\n"
                    f"【重要：你的上半篇前文参考 (请顺着语气接着写)】：\n{part1_draft}\n"
                    f"任务：紧接上半篇的情绪和动作，完成下半篇的正文。目标字数 {target_words_p2} 字左右。\n"
                    f"🚨 绝对红线：严禁重复上半篇已经写过的剧情！严厉执行结尾钩子规则！"
                )
                messages_p2 = [SystemMessage(content=sys_prompt_part2), HumanMessage(content=instr_part2)]

                part2_draft = ""
                if config:
                    async for chunk in llm.astream(messages_p2, config=config):
                        part2_draft += chunk.content
                else:
                    response = await llm.ainvoke(messages_p2)
                    part2_draft = response.content

                new_draft = part1_draft + part2_draft
            else:
                sys_prompt_text = self.load_prompt(
                    recent_chapters_summary=recent_chapters_summary,
                    scene_hook_prompt=scene_hook_prompt,
                    world_bible=world_bible,
                    history_context=history_context,
                    style_guide=style_guide,
                    examples_str=examples_str,
                    dynamic_hook_rule=dynamic_hook_rule
                )[0].content
                instruction = (
                    f"【首次生成指令】\n"
                    f"这是本章的大纲：\n{current_beat_sheet}\n"
                    f"任务：请严格按照大纲给定的情节走向和爽点要求生成初稿，目标 2000 字左右。"
                )
                formatted_messages = [SystemMessage(content=sys_prompt_text), HumanMessage(content=instruction)]
                if config:
                    async for chunk in llm.astream(formatted_messages, config=config):
                        new_draft += chunk.content
                else:
                    response = await llm.ainvoke(formatted_messages)
                    new_draft = response.content

        print(f"✅ [Chapter-Writer] 码字完毕，总字数：{len(new_draft)}")
        draft_path = os.path.join(settings.DATA_DIR, current_book_id, f"temp_draft_{current_chapter_num}.txt")
        os.makedirs(os.path.dirname(draft_path), exist_ok=True)

        with open(draft_path, "w", encoding="utf-8") as f:
            f.write(new_draft)

        return {
            "draft_path": draft_path,
            "human_approval_status": "PENDING"
        }


@register("chapter_writer")
async def chapter_writer_node(state: dict, config: RunnableConfig = None) -> Dict[str, Any]:
    agent = ChapterWriterAgent()
    return await agent.execute(state, config)
