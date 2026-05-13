# app/agents/base.py
import json
import re
import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Type

from pydantic import BaseModel
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from jinja2 import Template

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


class BaseAgent(ABC):
    """Abstract base for all workflow agents. Subclasses define name, prompt_file, and execute()."""

    name: str
    prompt_file: str

    @abstractmethod
    async def execute(self, state: dict) -> Dict[str, Any]:
        """Core entry point. Receives full state dict, returns partial state dict."""
        ...

    def load_prompt(self, **kwargs) -> list:
        """Load YAML prompt file and interpolate variables via Jinja2."""
        import yaml
        file_path = PROMPTS_DIR / self.prompt_file
        if not file_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        system_text = data.get("system_prompt", "")
        human_text = data.get("human_prompt_template", "") if isinstance(data, dict) else ""
        system_rendered = Template(system_text).render(**kwargs)
        human_rendered = Template(human_text).render(**kwargs) if human_text else ""
        messages = [SystemMessage(content=system_rendered)]
        if human_rendered:
            messages.append(HumanMessage(content=human_rendered))
        return messages

    @staticmethod
    def extract_json(text: str) -> str:
        """Extract JSON string from LLM response, supporting markdown code blocks and bare JSON."""
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            return m.group(1).strip()
        start = text.find('{')
        if start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1].strip()
        return text.strip()

    async def safe_json_invoke(self, llm, prompt_messages: list, model_cls: Type[BaseModel],
                                max_retries: int = 3, timeout: int = 180) -> BaseModel:
        """Safely invoke LLM to produce JSON, parse as Pydantic model with retries."""
        schema_str = json.dumps(model_cls.model_json_schema(), ensure_ascii=False, indent=2)
        schema_instruction = (
            f"\n\n【强约束格式要求】：\n"
            f"你必须且只能输出一个符合以下 JSON Schema 的 JSON 对象。\n"
            f"绝对不要遗漏任何必填字段，字段类型必须严格一致：\n"
            f"{schema_str}"
        )
        messages_to_send = list(prompt_messages)
        last_msg = messages_to_send[-1]
        if hasattr(last_msg, 'content'):
            messages_to_send[-1] = type(last_msg)(content=last_msg.content + schema_instruction)

        for attempt in range(max_retries):
            try:
                print(f"[{self.name}] 大模型推演中 (第 {attempt + 1}/{max_retries} 次)...", flush=True)
                response = await asyncio.wait_for(llm.ainvoke(messages_to_send), timeout=timeout)
                print(f"[{self.name}] 大模型推演完成，正在解析结果...", flush=True)
                json_str = self.extract_json(response.content)
                result = model_cls.model_validate_json(json_str)
                print(f"[{self.name}] 推演结果解析成功！", flush=True)
                return result
            except asyncio.TimeoutError:
                print(f"[{self.name}] 第 {attempt + 1} 次调用超时 ({timeout}秒)", flush=True)
                if attempt < max_retries - 1:
                    messages_to_send.append(HumanMessage(content="上次调用超时，请直接输出 JSON，不要任何额外文本。"))
            except Exception as e:
                print(f"[{self.name}] 第 {attempt + 1} 次调用/解析失败: {e}", flush=True)
                if attempt < max_retries - 1:
                    messages_to_send.append(AIMessage(content=f"你的输出格式有误: {str(e)}"))
                    messages_to_send.append(HumanMessage(
                        content=f"请严格按照以下 JSON Schema 重新输出完整的 JSON。不要自己发明字段名！\n报错信息：{str(e)}\n{schema_instruction}"))

        raise ValueError(f"[{self.name}] 在 {max_retries} 次重试后仍然失败")
