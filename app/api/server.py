# 生命周期管理 (Lifespan)，预热数据库与向量引擎
# app/api/server.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.memory.kv_tracker import KVTracker
from app.memory.rag_engine import RAGEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    生命周期管理：服务启动时预热数据库与向量引擎
    """
    print("🚀 [Server] 正在启动 StoryWeaver 共创引擎...")
    try:
        print("📦 [Server] 正在连接/初始化 KV 状态数据库...")
        KVTracker()  # 触发 config.py 中的路径校验与初始化

        print("📚 [Server] 正在连接/预热 RAG 向量存储空间...")
        RAGEngine()  # 同上，预先拉起 FAISS 索引
    except Exception as e:
        print(f"⚠️ [Server] 引擎预热异常，但不阻断启动: {e}")

    yield  # 服务在此处保持运行

    print("🛑 [Server] 正在关闭 StoryWeaver 共创引擎...")


# 初始化 FastAPI 实例
app = FastAPI(
    title="StoryWeaver-Agent API",
    description="工业级长篇小说共创引擎 (番茄网文定制版)",
    version="1.0.0",
    lifespan=lifespan
)

# 配置 CORS 跨域，允许 Streamlit 或其他前端框架无缝调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载路由
app.include_router(router)