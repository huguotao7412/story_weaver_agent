# app/agents/base.py
import asyncio
import yaml
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, Type

from pydantic import BaseModel
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from jinja2 import Template

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


@lru_cache(maxsize=32)
def _read_yaml_prompt(file_path: Path) -> dict:
    """缓存 YAML 文件读取，避免高频并发下的磁盘 I/O 瓶颈。"""
    if not file_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class BaseAgent(ABC):
    """Abstract base for all workflow agents. Subclasses define name, prompt_file, and execute()."""

    name: str
    prompt_file: str

    @abstractmethod
    async def execute(self, state: dict) -> Dict[str, Any]:
        """Core entry point. Receives full state dict, returns partial state dict."""
        ...

    def load_prompt(self, **kwargs) -> list:
        """Load YAML prompt file (cached) and interpolate variables via Jinja2."""
        file_path = PROMPTS_DIR / self.prompt_file
        data = _read_yaml_prompt(file_path)
        system_text = data.get("system_prompt", "")
        human_text = data.get("human_prompt_template", "") if isinstance(data, dict) else ""
        system_rendered = Template(system_text).render(**kwargs)
        human_rendered = Template(human_text).render(**kwargs) if human_text else ""
        messages = [SystemMessage(content=system_rendered)]
        if human_rendered:
            messages.append(HumanMessage(content=human_rendered))
        return messages

    async def safe_json_invoke(self, llm, prompt_messages: list, model_cls: Type[BaseModel],
                                max_retries: int = 3, timeout: int = 180) -> BaseModel:
        """使用大模型原生结构化输出能力 (with_structured_output)，替代手写 JSON Schema 注入。"""
        structured_llm = llm.with_structured_output(model_cls)
        messages_to_send = list(prompt_messages)

        for attempt in range(max_retries):
            try:
                print(f"[{self.name}] 大模型推演中 (原生结构化模式, 第 {attempt + 1}/{max_retries} 次)...", flush=True)
                result = await asyncio.wait_for(structured_llm.ainvoke(messages_to_send), timeout=timeout)
                print(f"[{self.name}] 结构化解析成功！", flush=True)
                return result
            except asyncio.TimeoutError:
                print(f"[{self.name}] 第 {attempt + 1} 次调用超时 ({timeout}秒)", flush=True)
                if attempt < max_retries - 1:
                    messages_to_send.append(HumanMessage(content="上次调用超时，请直接输出符合要求的 JSON。"))
            except Exception as e:
                    print(f"[{self.name}] 第 {attempt + 1} 次推演失败: {e}", flush=True)
                    if attempt < max_retries - 1:
                        messages_to_send.append(AIMessage(content=f"生成中断或结构化解析失败。"))
                        messages_to_send.append(HumanMessage(
                            content=f"请严格按照之前要求的 JSON Schema 重新输出。报错细节: {str(e)}"
                        ))
                        # 🌟 修复：加入指数退避等待，避免重试雪崩 (2秒, 4秒...)
                        sleep_time = 2 ** (attempt + 1)
                        print(f"[{self.name}] 触发防雪崩机制，休眠 {sleep_time} 秒后重试...", flush=True)
                        await asyncio.sleep(sleep_time)

        raise ValueError(f"[{self.name}] 在 {max_retries} 次重试后仍然失败")
