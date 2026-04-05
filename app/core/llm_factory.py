# app/core/llm_factory.py
import os
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from dotenv import load_dotenv

# 确保在实例化前加载 .env 文件中的环境变量
load_dotenv()

def get_llm(model_type: str = "main", temperature: float = None) -> ChatOpenAI:
    """
    统一的大语言模型 (LLM) 工厂函数
    """
    if model_type == "fast":
        api_key = os.getenv("FAST_LLM_API_KEY")
        base_url = os.getenv("FAST_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
        model_name = os.getenv("FAST_LLM_MODEL_NAME", "glm-4-flash")
        default_temp = 0.2
    elif model_type == "main":
        api_key = os.getenv("MAIN_LLM_API_KEY")
        base_url = os.getenv("MAIN_LLM_BASE_URL", "https://api.deepseek.com/v1")
        model_name = os.getenv("MAIN_LLM_MODEL_NAME", "deepseek-chat")
        default_temp = 0.4
    else:
        raise ValueError(f"未知的 model_type: {model_type}")

    if not api_key:
        raise ValueError(f"【环境配置错误】缺少 {model_type} 模型的 API KEY，请检查 .env 文件。")

    final_temp = temperature if temperature is not None else default_temp

    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model_name,
        temperature=final_temp,
        max_retries=2,
        timeout=240
    )

def get_embeddings() -> OpenAIEmbeddings:
    """
    统一的向量模型 (Embedding) 工厂函数，专为硅基流动等兼容 OpenAI 接口的服务设计
    """
    api_key = os.getenv("EMBEDDING_API_KEY")
    base_url = os.getenv("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
    model_name = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")

    if not api_key:
        raise ValueError("【环境配置错误】缺少 Embedding 模型的 API KEY，请检查 .env 文件。")

    # 硅基流动的 Embedding 接口完全兼容 OpenAIEmbeddings
    return OpenAIEmbeddings(
        api_key=api_key,
        base_url=base_url,
        model=model_name,
    )