# app/api/server.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app.core.config import settings

from app.api.routes import router
from app.memory.rag_engine import RAGEngine
from app.agents.graph import build_workflow

DB_PATH = os.path.join(settings.DATA_DIR, "checkpoints.sqlite")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    生命周期管理：服务启动时预热数据库与向量引擎，并维持全局记忆库连接
    """
    print("🚀 [Server] 正在启动 StoryWeaver 共创引擎...")
    try:
        print("📦 [Server] 正在连接/初始化 KV 状态数据库...")
        print("📚 [Server] 正在连接/预热 RAG 向量存储空间...")
        RAGEngine()
    except Exception as e:
        print(f"⚠️ [Server] 引擎预热异常，但不阻断启动: {e}")

    # 🌟 核心修改：将 Checkpointer 提升到全局生命周期，挂载到 app.state
    print("💾 [Server] 正在挂载全局 LangGraph 记忆库连接池...")
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as memory:
        app.state.checkpoint_saver = memory
        print("⚙️ [Server] 正在全局编译 LangGraph 引擎实例...")
        workflow = build_workflow()
        app.state.storyweaver_app = workflow.compile(
            checkpointer=memory,
            interrupt_before=["Chapter_Writer", "Human_Review"]
        )
        print("✅ [Server] 引擎预热并编译完成！")

        yield  # 服务在此处保持运行，数据库连接在此期间一直保持开启！

    print("🛑 [Server] 正在关闭 StoryWeaver 共创引擎，释放数据库连接...")


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