# app/agents/workers/style_analyzer.py

import json
import re
import asyncio
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import get_llm
from protocols.a2a_schemas import StyleGuide  # 🌟 引入协议层的 Pydantic Schema

STYLE_ANALYSIS_PROMPT = """你是一个顶尖的网文"文风解构师"。
你的任务是零样本读取用户上传的【神作片段】，从多个维度解构并提炼出《文风白皮书》，作为后续小说生成的底层基因。

注意：
1. 你的分析必须极其敏锐，能捕捉到下沉市场网文的"爽感"来源。
2. 请严格按照系统提供的结构返回合法的 JSON 数据，绝对禁止包含任何 Markdown 代码块包裹或前缀废话。
3. 【极其重要】：你必须在 `example_snippets` 字段中，直接摘抄原文本中 1-2 段最具网文"爽点"、镜头感最好、最能体现该文风的真实段落（每段 100 字左右）。我们将把这些片段作为示例(Few-shot)直接喂给主笔，让它模仿这种行文感觉！
"""


async def style_analyzer_node(state: dict) -> Dict[str, Any]:
    """
    🎭 Style-Analyzer (文风解构师)
    提取参考片段的文风，并持久化到 target_writing_style 共享状态中。
    """

    # 🌟 核心修改点：不需要再写循环去 messages 里找了，直接从 state 获取文本
    reference_text = state.get("user_input", "")

    # 如果没有找到参考文本，则跳过提取（或者返回默认文风）
    if not reference_text:
        return {}

    # 实例化 LLM
    llm = get_llm(temperature=0.1)

    # 组装 Prompt
    formatted_messages = [
        SystemMessage(content=STYLE_ANALYSIS_PROMPT),
        HumanMessage(content=f"【用户提供的参考神作片段】\n{reference_text}")
    ]

    try:
        # 调用模型并手动解析 JSON
        print(f"⏳ [Style-Analyzer] 正在调用大模型分析文风...")
        response = await asyncio.wait_for(llm.ainvoke(formatted_messages), timeout=180)

        content = response.content
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        json_str = m.group(1).strip() if m else content.strip()
        if not json_str.startswith('{'):
            m2 = re.search(r'\{.*\}', content, re.DOTALL)
            if m2:
                json_str = m2.group(0).strip()

        style_result: StyleGuide = StyleGuide.model_validate_json(json_str)
        style_guide_dict = style_result.model_dump()
        print("🎭 [Style-Analyzer] 文风解构成功！")
    except Exception as e:
        print(f"⚠️ [Style-Analyzer] 结构化解析失败，使用默认容错文风: {e}")
        style_guide_dict = {
            "tone": "未知",
            "sentence_structure": "未知",
            "vocabulary": "未知",
            "action_dialogue_ratio": "未知",
            "compiled_prompt": "通俗口语化，极快节奏的网文爽文风"
        }

    # 持久化规则到共享状态
    updated_style_info = {
        "novel_specific": {
            "rules": style_guide_dict,
            "has_been_analyzed": True
        }
    }

    return {"target_writing_style": updated_style_info}