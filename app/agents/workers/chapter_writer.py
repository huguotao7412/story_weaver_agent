# app/agents/workers/chapter_writer.py
import os
import json
import re
from typing import Dict, Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agents.base import BaseAgent
from app.core.config import settings
from app.core.llm_factory import get_llm
from app.memory.kv_tracker import AsyncKVTracker
from app.agents.registry import register


class ChapterWriterAgent(BaseAgent):
    name = "Chapter_Writer"
    prompt_file = "chapter_writer.yaml"

    async def execute(self, state: dict, config: RunnableConfig = None) -> Dict[str, Any]:
        current_chapter_num = state.get("current_chapter_num", 1)
        current_book_id = state.get("book_id", "default_book")
        prev_ending = state.get("previous_chapter_ending", "")

        tracker = AsyncKVTracker(book_id=current_book_id)
        await tracker.init_db()

        world_bible = await tracker.get_temp_context("world_bible", "暂无宏观世界观。")
        current_beat_sheet = await tracker.get_temp_context("beat_sheet", "暂无大纲。")
        history_context = await tracker.get_temp_context("rag_history", "暂无历史剧情。")

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

        # 辅助函数：加载 SystemPrompt（静态冷数据）+ HumanPrompt（动态热数据）
        def _build_messages(extra_instruction: str, hook_override: str = None) -> list:
            hook = hook_override if hook_override is not None else scene_hook_prompt
            loaded = self.load_prompt(
                recent_chapters_summary=recent_chapters_summary,
                scene_hook_prompt=hook,
                world_bible=world_bible,
                history_context=history_context,
                style_guide=style_guide,
                examples_str=examples_str,
                dynamic_hook_rule=dynamic_hook_rule
            )
            return [loaded[0], HumanMessage(content=loaded[1].content + "\n\n" + extra_instruction)]

        if is_rewrite:
            if human_status == "REJECTED":
                print("✍️ [Chapter-Writer] 收到人类总编【打回重写】指令，正在后台含泪重构...")
                extra_instruction = (
                    f"【🔥 最高指令：人类总编打回重写】\n"
                    f"人类总编严厉批注：{human_feedback}\n"
                    f"以下是本章经历的历史打回记录与建议（请避开同样的错误）：\n{history_text}\n\n"
                    f"你的原稿如下：\n{current_draft}\n\n"
                    f"任务：请仔细揣摩总编意图，抛弃原稿不合理部分，结合大纲彻底重写本章正文。务必让总编满意！"
                )
            else:
                print(f"✍️ [Chapter-Writer] 收到内审打回指令，正在疯狂填补细节注水...")
                extra_instruction = (
                    f"【⚠️ 内部质检打回重写】\n"
                    f"以下是主编(内审组)的打回意见栈：\n{history_text}\n\n"
                    f"你的原稿如下：\n{current_draft}\n\n"
                    f"任务：仔细阅读内审意见！绝对禁止往后推时间线抢跑！如果字数不够，请在节拍器要求的高权重画面疯狂加环境白描与心理戏！彻底重写。"
                )

            formatted_messages = _build_messages(extra_instruction)
            if config:
                async for chunk in llm.astream(formatted_messages, config=config):
                    new_draft += chunk.content
            else:
                response = await llm.ainvoke(formatted_messages)
                new_draft = response.content

        else:
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
                print(f"✍️ [Chapter-Writer] 正在执行动态滑动窗口分段码字...")
                chunk_size = 2
                current_hook = scene_hook_prompt

                for i in range(0, len(beats), chunk_size):
                    current_chunk_beats = beats[i:i + chunk_size]
                    chunk_outline = json.dumps({"beats": current_chunk_beats}, ensure_ascii=False, indent=2)

                    try:
                        weight_sum = sum(
                            [float(str(b.get("word_count_weight", "0")).replace("%", "")) for b in current_chunk_beats])
                        target_words = max(int((weight_sum / 100) * settings.MAX_WORDS_PER_CHAPTER), 600)
                    except:
                        target_words = 1500

                    chunk_idx = i // chunk_size + 1
                    print(f"   [Chunk {chunk_idx}] 正在生成节拍 {i + 1} 至 {min(i + chunk_size, len(beats))} (目标字数: ~{target_words}字)...")

                    extra_instruction = (
                        f"【第 {chunk_idx} 部分生成指令】\n"
                        f"这是你当前要专注完成的微观节拍器：\n{chunk_outline}\n"
                        f"任务：请严格按照这部分大纲，生成正文。目标字数 {target_words} 字左右。\n"
                        f"🚨 绝对红线：只能推进到当前大纲节点！必须用冰山理论填满细节！"
                    )

                    messages = _build_messages(extra_instruction, hook_override=current_hook)

                    chunk_draft = ""
                    if config:
                        async for chunk in llm.astream(messages, config=config):
                            chunk_draft += chunk.content
                    else:
                        response = await llm.ainvoke(messages)
                        chunk_draft = response.content

                    new_draft += chunk_draft + "\n\n"

                    # 滑动窗口核心：提取最后 500 字作为下一轮的接续锚点
                    clean_chunk = chunk_draft.strip()
                    tail_text = clean_chunk[-500:] if len(clean_chunk) > 500 else clean_chunk
                    current_hook = f"前文最后 500 字参考（请直接顺着语气和动作往下写，绝不可另起炉灶）：\n《...{tail_text}》"

                print(f"✅ [Chapter-Writer] 动态滑动窗口码字完毕，总字数：{len(new_draft)}")
            else:
                extra_instruction = (
                    f"【首次生成指令】\n"
                    f"这是本章的大纲：\n{current_beat_sheet}\n"
                    f"任务：请严格按照大纲给定的情节走向和爽点要求生成初稿，目标 2000 字左右。"
                )
                formatted_messages = _build_messages(extra_instruction)
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
