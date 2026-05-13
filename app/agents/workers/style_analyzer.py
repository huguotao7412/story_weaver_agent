# app/agents/workers/style_analyzer.py
import json
import re
import asyncio
from typing import Dict, Any

from langchain_core.messages import HumanMessage

from app.agents.base import BaseAgent
from app.core.llm_factory import get_llm
from app.agents.registry import register
from protocols.a2a_schemas import StyleGuide


class StyleAnalyzerAgent(BaseAgent):
    name = "Style_Analyzer"
    prompt_file = "style_analyzer.yaml"

    async def execute(self, state: dict) -> Dict[str, Any]:
        reference_text = state.get("user_input", "")

        if not reference_text:
            return {}

        llm = get_llm(temperature=0.1)
        schema_str = json.dumps(StyleGuide.model_json_schema(), ensure_ascii=False, indent=2)

        messages = self.load_prompt()
        messages.append(HumanMessage(
            content=(
                f"【用户提供的参考神作片段】\n{reference_text}\n\n"
                f"🚨 【强约束格式要求】：\n"
                f"你必须且只能输出一个符合以下 JSON Schema 的完整 JSON 对象。请勿添加任何多余的解释说明文本：\n"
                f"{schema_str}"
            )
        ))

        try:
            print(f"⏳ [Style-Analyzer] 正在调用大模型分析文风...")
            response = await asyncio.wait_for(llm.ainvoke(messages), timeout=180)

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

        updated_style_info = {
            "novel_specific": {
                "rules": style_guide_dict,
                "has_been_analyzed": True
            }
        }

        return {"target_writing_style": updated_style_info}


@register("style_analyzer")
async def style_analyzer_node(state: dict) -> Dict[str, Any]:
    agent = StyleAnalyzerAgent()
    return await agent.execute(state)
