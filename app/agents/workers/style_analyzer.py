# app/agents/workers/style_analyzer.py

import json
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import get_llm
from protocols.a2a_schemas import StyleGuide  # 🌟 引入协议层的 Pydantic Schema

STYLE_ANALYSIS_PROMPT = """你是一个顶尖的网文“文风解构师”。
你的任务是零样本读取用户上传的【神作片段】，从多个维度解构并提炼出《文风白皮书》，作为后续小说生成的底层基因。

注意：
1. 你的分析必须极其敏锐，能捕捉到下沉市场网文的“爽感”来源。
2. 请严格按照系统提供的结构 (Schema) 返回合法的数据，绝对禁止包含任何 Markdown 代码块包裹或前缀废话。
"""


async def style_analyzer_node(state: dict) -> Dict[str, Any]:
    """
    🎭 Style-Analyzer (文风解构师)
    提取参考片段的文风，并持久化到 target_writing_style 共享状态中。
    """
    messages = state.get("messages", [])

    # 寻找用户最新上传的参考文本
    reference_text = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            reference_text = m.content
            break

    # 如果没有找到参考文本，则跳过提取（或者返回默认文风）
    if not reference_text:
        return {}

    # 实例化 LLM
    llm = get_llm(model_type="main", temperature=0.1)

    # 🌟 核心修改：绑定 Pydantic Schema 进行结构化输出
    structured_llm = llm.with_structured_output(StyleGuide)

    # 组装 Prompt
    formatted_messages = [
        SystemMessage(content=STYLE_ANALYSIS_PROMPT),
        HumanMessage(content=f"【用户提供的参考神作片段】\n{reference_text}")
    ]

    try:
        # 调用模型并直接获取 Pydantic 对象
        style_result: StyleGuide = await structured_llm.ainvoke(formatted_messages)
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