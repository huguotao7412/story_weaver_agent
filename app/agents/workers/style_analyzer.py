# 🎭 文风解构师：提取参考文风并生成白皮书
# app/agents/workers/style_analyzer.py

import json
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage

# 引入你写的 LLM 工厂
from app.core.llm_factory import get_llm

STYLE_ANALYSIS_PROMPT = """你是一个顶尖的网文“文风解构师”。
你的任务是零样本读取用户上传的【神作片段】，从多个维度解构并提炼出《文风白皮书》，作为后续小说生成的底层基因。

请分析以下维度，并严格以 JSON 格式输出：
{
    "tone": "整体基调，例如：轻松、沉重、冷血、极快节奏",
    "sentence_structure": "句式特征，例如：大量短句、感叹号丰富、喜欢用倒装",
    "vocabulary": "用词偏好，例如：通俗大白话、下沉市场网络梗、文言文交织",
    "action_dialogue_ratio": "动静比，对话与动作描写的比例偏好",
    "compiled_prompt": "基于以上4点，提炼出一段供后续 'AI金牌主笔' 节点直接使用的系统级文风 Prompt 强指令"
}

注意：
1. 你的分析必须极其敏锐，能捕捉到下沉市场网文的“爽感”来源。
2. 只返回合法的 JSON 字符串，不要包含任何 Markdown 代码块包裹（如 ```json ），直接输出大括号开头和结尾的内容。
"""


def style_analyzer_node(state: dict) -> Dict[str, Any]:
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

    # 实例化 LLM：根据你的 llm_factory，"main" 对应 DeepSeek-Chat，非常适合结构化特征提取
    llm = get_llm(model_type="main", temperature=0.1)

    # 组装 Prompt
    formatted_messages = [
        SystemMessage(content=STYLE_ANALYSIS_PROMPT),
        HumanMessage(content=f"【用户提供的参考神作片段】\n{reference_text}")
    ]

    # 调用模型
    response = llm.invoke(formatted_messages)
    content = response.content.strip()

    # 清理可能残留的 markdown 标签
    if content.startswith("```json"):
        content = content[7:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    # 解析文风特征
    try:
        style_guide_dict = json.loads(content)
    except json.JSONDecodeError:
        # Fallback 容错：如果 JSON 解析失败，将原始内容直接塞入指令中
        style_guide_dict = {
            "tone": "未知",
            "sentence_structure": "未知",
            "vocabulary": "未知",
            "action_dialogue_ratio": "未知",
            "compiled_prompt": f"请参考以下文风特征：{content}"
        }

    # 参考 content_writer 的做法，利用 dict 结构持久化规则
    # 返回的内容将自动更新并持久化到 SharedValue 中
    updated_style_info = {
        "novel_specific": {
            "rules": style_guide_dict,
            "has_been_analyzed": True
        }
    }

    # 返回局部更新，LangGraph 会自动合并到 state["target_writing_style"] 中
    return {"target_writing_style": updated_style_info}