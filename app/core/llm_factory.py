# app/core/llm_factory.py
import os
import requests
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from dotenv import load_dotenv
from typing import List

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


def rerank_documents(query: str, documents: List[str], top_n: int = 3) -> List[int]:
    """
    🥇 硅基流动 Rerank 交叉编码器重排序
    输入查询和文档列表，返回按相关性从高到低排序后的文档【索引列表】
    """
    if not documents:
        return []

    api_key = os.getenv("RERANK_API_KEY")
    # 硅基流动的 Rerank 标准接口
    rerank_url = "https://api.siliconflow.cn/v1/rerank"

    if not api_key:
        print("⚠️ [Rerank] 缺少 EMBEDDING_API_KEY，降级为原顺序返回")
        return list(range(min(top_n, len(documents))))

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "BAAI/bge-reranker-v2-m3",  # 硅基流动提供的免费且强大的多语言重排模型
        "query": query,
        "documents": documents,
        "top_n": top_n,
        "return_documents": False  # 节省带宽，只返回索引和分数
    }

    try:
        response = requests.post(rerank_url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # 解析返回结果，提取重排后的索引
        # data["results"] 的格式如：[{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}, ...]
        sorted_indices = [item["index"] for item in data.get("results", [])]
        return sorted_indices
    except Exception as e:
        print(f"⚠️ [Rerank] API 调用失败: {e}，降级为原顺序返回")
        # 容错：如果 API 崩了，直接返回前 top_n 个原索引
        return list(range(min(top_n, len(documents))))