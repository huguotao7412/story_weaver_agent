# 定义 /novel/stream (流式生成) 与 /novel/feedback (接收总编意见)
# app/api/routes.py

import os
import json
import shutil
import aiosqlite
from typing import Optional, Literal, Dict, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

# 🌟 新增：导入异步版 SqliteSaver 和配置
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app.core.config import settings
from app.agents.workers.style_analyzer import style_analyzer_node
from app.agents.graph import build_workflow  # 导入工厂函数

router = APIRouter(prefix="/novel", tags=["Novel Workflow"])

# 全局数据库路径
DB_PATH = os.path.join(settings.DATA_DIR, "checkpoints.sqlite")


# === 数据模型定义 ===
class GenerateRequest(BaseModel):
    user_input: str
    thread_id: str = "story_thread_01"
    chapter_num: int = 1
    target_writing_style: Optional[Dict[str, Any]] = None
    predefined_world_bible: Optional[str] = ""


class StyleRequest(BaseModel):
    reference_text: str


class FeedbackRequest(BaseModel):
    thread_id: str = "story_thread_01"
    approval_status: Literal["APPROVED", "REJECTED"]
    human_feedback: Optional[str] = ""
    direct_edits: Optional[str] = ""
    # 🌟 新增：支持前置大纲修改与双断点定位
    edited_beat_sheet: Optional[str] = ""
    target_node: Literal["Human_Review", "Chapter_Writer"] = "Human_Review"


# === 接口 1：独立触发文风解构师 ===
@router.post("/analyze_style")
async def analyze_style_api(req: StyleRequest):
    try:
        state_mock = {"messages": [HumanMessage(content=req.reference_text)]}
        result = style_analyzer_node(state_mock)
        return {"status": "success", "style_guide": result.get("target_writing_style", {})}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文风提取失败: {str(e)}")


# === 核心接口 1：流式启动节点 (异步升级版) ===
@router.post("/stream")
async def generate_novel_stream(req: GenerateRequest):
    config = {"configurable": {"thread_id": req.thread_id}}

    initial_state = {
        "messages": [HumanMessage(content=req.user_input)],
        "current_chapter_num": req.chapter_num,
        "book_id": req.thread_id
    }

    if req.predefined_world_bible and req.predefined_world_bible.strip():
        initial_state["world_bible_context"] = req.predefined_world_bible

    if req.target_writing_style:
        initial_state["target_writing_style"] = req.target_writing_style

    async def event_generator():
        try:
            # 🌟 在请求内动态创建异步 DB 连接
            async with AsyncSqliteSaver.from_conn_string(DB_PATH) as memory:
                workflow = build_workflow()
                storyweaver_app = workflow.compile(
                    checkpointer=memory,
                    # 🌟 核心：注入双断点！写正文前挂起审大纲，审核前挂起审正文
                    interrupt_before=["Chapter_Writer", "Human_Review"]
                )

                current_state = await storyweaver_app.aget_state(config)
                run_input = None if current_state.next else initial_state

                async for event in storyweaver_app.astream(run_input, config=config):
                    node_name = list(event.keys())[0]
                    state_updates = event[node_name]

                    # 💡 修复点 1：剔除不需要传给前端 UI 的 messages，减轻网络负担
                    safe_updates = {k: v for k, v in state_updates.items() if k != "messages"}
                    payload = {"node": node_name, "updates": safe_updates}

                    # 💡 修复点 2：加上 default=str，强制将任何不可序列化对象转为字符串，防止程序崩溃
                    yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

                # 🌟 探测断点位置并给前端发送信号
                new_state = await storyweaver_app.aget_state(config)
                if new_state.next:
                    if "Chapter_Writer" in new_state.next:
                        yield "data: {\"status\": \"PAUSED_FOR_BEAT_SHEET_REVIEW\"}\n\n"
                    elif "Human_Review" in new_state.next:
                        yield "data: {\"status\": \"PAUSED_FOR_HUMAN_REVIEW\"}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# === 核心接口 2：接收人类总编反馈并唤醒 (双断点分流修复版) ===
@router.post("/feedback")
async def receive_human_feedback(req: FeedbackRequest):
    config = {"configurable": {"thread_id": req.thread_id}}

    try:
        async with AsyncSqliteSaver.from_conn_string(DB_PATH) as memory:
            workflow = build_workflow()
            storyweaver_app = workflow.compile(
                checkpointer=memory,
                interrupt_before=["Chapter_Writer", "Human_Review"]
            )

            current_state = await storyweaver_app.aget_state(config)
            if not current_state.next:
                raise HTTPException(status_code=400, detail="当前没有被挂起的任务。")

            # 🌟 分支 1：处理前置 HITL (大纲审批)
            if req.target_node == "Chapter_Writer" and "Chapter_Writer" in current_state.next:
                # 覆盖内部的节拍器大纲状态，此时无需步进，等待前端 /stream 重新唤醒
                await storyweaver_app.aupdate_state(config, {"current_beat_sheet": req.edited_beat_sheet})
                return {"status": "success", "message": "大纲已确认，准备流式生成正文。"}

            # 🌟 分支 2：处理后置 HITL (正文审批)
            elif req.target_node == "Human_Review" and "Human_Review" in current_state.next:
                human_decision = {
                    "human_approval_status": req.approval_status,
                    "human_feedback": req.human_feedback,
                    "direct_edits": req.direct_edits
                }

                # 注入人类决策
                await storyweaver_app.aupdate_state(config, human_decision)

                if req.approval_status == "APPROVED":
                    # 批准后，消耗掉剩下的保存事件
                    async for _ in storyweaver_app.astream(None, config=config):
                        pass
                else:
                    # 打回重写时，手动步进一次，跨过 Human_Review 节点
                    async for event in storyweaver_app.astream(None, config=config):
                        if "Human_Review" not in event:
                            break
                return {"status": "success", "message": "正文反馈已接收，已同步至状态机。",
                        "approval": req.approval_status}

            else:
                raise HTTPException(status_code=400, detail="目标节点与当前挂起状态不匹配。")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"唤醒执行失败: {str(e)}")


# === 核心接口 3：获取当前所有书籍列表 ===
@router.get("/books")
async def list_books():
    if not os.path.exists(settings.DATA_DIR):
        return {"books": []}

    books = []
    for item in os.listdir(settings.DATA_DIR):
        item_path = os.path.join(settings.DATA_DIR, item)
        # 排除全局文件夹和SQLite文件，只取书籍沙盒目录
        if os.path.isdir(item_path) and item not in ["references", "raw_drafts"]:
            books.append(item)
    return {"books": books}


# === 核心接口 4：彻底销毁某本书的全部数据 ===
@router.delete("/books/{book_id}")
async def delete_book(book_id: str):
    # 1. 物理销毁文件（FAISS向量、TinyDB、Markdown草稿）
    book_dir = os.path.join(settings.DATA_DIR, book_id)
    if os.path.exists(book_dir):
        try:
            # 🌟【核心修复 3】：加入 ignore_errors=True
            # 强行忽略由于 TinyDB 文件句柄未释放导致的 Windows 权限报错
            shutil.rmtree(book_dir, ignore_errors=True)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"文件清理失败: {str(e)}")

    # 2. 清理 LangGraph 的 SQLite 记忆库
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # 🌟【核心修复 4】：修正 LangGraph V0.2 的底层表结构命名
            await db.execute("DELETE FROM checkpoints WHERE thread_id = ?", (book_id,))
            await db.execute("DELETE FROM checkpoint_writes WHERE thread_id = ?", (book_id,))
            await db.execute("DELETE FROM checkpoint_blobs WHERE thread_id = ?", (book_id,))
            await db.commit()
    except Exception as e:
        print(f"⚠️ SQLite 清理遇到阻碍: {e}")

    return {"status": "success", "message": f"书籍 {book_id} 已被彻底超度。"}