# main.py
import uvicorn
import os
import sys
from pathlib import Path

# 确保项目根目录被加入 Python 环境变量，防止找不到 app 模块
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT))


def print_startup_banner():
    """打印酷炫的启动提示语"""
    banner = """
    ========================================================
    📖 StoryWeaver-Agent (工业级小说共创引擎) 启动中...

    👑 架构: LangGraph 多智能体 + FastAPI 后端 + RAG 记忆
    ========================================================
    """
    print(banner)
    print("🚀 [Backend] FastAPI 服务即将运行在: http://127.0.0.1:8000")
    print("📜 [API Docs] 接口文档请访问: http://127.0.0.1:8000/docs")
    print("-" * 56)
    print("💡 [Frontend] 提示: 若要进入“人类总编操作台”，")
    print("   请新开一个终端窗口，并在项目根目录下运行:")
    print("   👉 streamlit run ui.py ")
    print("========================================================\n")


if __name__ == "__main__":
    print_startup_banner()

    # 启动 Uvicorn 服务器来托管 FastAPI 应用
    # 注意："app.api.server:app" 对应的是 app/api/server.py 里的 app = FastAPI() 实例
    uvicorn.run(
        "app.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # 开启代码热更新（开发模式下极大提升体验）
        log_level="info"  # 日志级别
    )