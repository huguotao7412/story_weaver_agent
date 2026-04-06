# app/api/routes.py

import os
import json
import shutil
import aiosqlite
from typing import Optional, Literal, Dict, Any
from fastapi import APIRouter, HTTPException, Request
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
    reference_text: Optional[str] = ""
    reference_filename: Optional[str] = ""


class FeedbackRequest(BaseModel):
    thread_id: str = "story_thread_01"
    chapter_num: int = 1  # 🌟 修复点：必须接收章节号，以便后端拼接 graph_thread_id
    approval_status: Literal["APPROVED", "REJECTED"]
    human_feedback: Optional[str] = ""
    direct_edits: Optional[str] = ""
    edited_beat_sheet: Optional[str] = ""
    target_node: Literal["Human_Review", "Chapter_Writer"] = "Human_Review"


@router.get("/references")
async def list_references():
    """扫描并返回所有已保存的历史参考神作文件"""
    if not os.path.exists(settings.REFERENCES_DIR):
        return {"files": []}
    # 过滤出所有 txt 文件
    files = [f for f in os.listdir(settings.REFERENCES_DIR) if f.endswith('.txt')]
    return {"files": files}


# --- 3. 改造原有接口：文风解构师 ---
@router.post("/analyze_style")
async def analyze_style_api(req: StyleRequest):
    try:
        text_to_analyze = req.reference_text

        if req.reference_filename:
            file_path = os.path.join(settings.REFERENCES_DIR, req.reference_filename)
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    text_to_analyze = f.read()
            else:
                raise HTTPException(status_code=404, detail="参考文件不存在于历史库中")

        if not text_to_analyze:
            raise HTTPException(status_code=400, detail="未提供任何参考文本或文件名")

        state_mock = {"messages": [HumanMessage(content=text_to_analyze)]}
        result = await style_analyzer_node(state_mock)

        return {"status": "success", "style_guide": result.get("target_writing_style", {})}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文风提取失败: {str(e)}")


@router.get("/books/{book_id}/progress")
async def get_book_progress(book_id: str):
    """扫描沙盒，获取下一章的预期章节号，实现真正的断点续写"""
    archive_dir = os.path.join(settings.DATA_DIR, book_id, "chapter_archive")
    if not os.path.exists(archive_dir):
        return {"next_chapter": 1}

    max_chapter = 0
    for filename in os.listdir(archive_dir):
        if filename.startswith("chapter_") and filename.endswith(".md"):
            try:
                num_str = filename.split("_")[1].split(".")[0]
                num = int(num_str)
                if num > max_chapter:
                    max_chapter = num
            except:
                continue
    return {"next_chapter": max_chapter + 1}


# === 核心接口 1：流式启动节点 (异步升级版) ===
@router.post("/stream")
async def generate_novel_stream(req: GenerateRequest, request: Request):  # 🌟 添加 request 依赖
    graph_thread_id = req.thread_id
    config = {"configurable": {"thread_id": graph_thread_id}}

    # 🌟 核心修改：直接从全局获取记忆池，避免在此处重新创建销毁
    memory = request.app.state.checkpoint_saver

    async def event_generator():
        try:
            # 🌟 核心修改：去掉了 async with 块，下面的代码整体向左缩进一层
            storyweaver_app = request.app.state.storyweaver_app

            # 获取当前这本书在数据库里的沉淀状态
            current_state = await storyweaver_app.aget_state(config)

            if not current_state.next:
                # 🌟 场景 A：这是一本新书，或者上一章已经顺利跑到 END 完结了
                run_input = {
                    "messages": [HumanMessage(content=req.user_input)],
                    "current_chapter_num": req.chapter_num,
                    "book_id": req.thread_id
                }
                if current_state and current_state.values:
                    old_values = current_state.values

                    # 核心防遗忘：继承前三层规划
                    if "book_outline_context" in old_values:
                        run_input["book_outline_context"] = old_values["book_outline_context"]
                    if "current_volume_phases" in old_values:
                        run_input["current_volume_phases"] = old_values["current_volume_phases"]
                    if "current_phase_chapters" in old_values:
                        run_input["current_phase_chapters"] = old_values["current_phase_chapters"]

                    # 核心防遗忘：继承世界观和文风（前提是本次请求没有传新的覆盖它）
                    if "world_bible_context" in old_values and not req.predefined_world_bible:
                        run_input["world_bible_context"] = old_values["world_bible_context"]
                    if "target_writing_style" in old_values and not req.target_writing_style:
                        run_input["target_writing_style"] = old_values["target_writing_style"]
                    # ==============================================================

                    # 如果用户在前端强制传了新的世界观或文风，则覆盖进去
                if req.predefined_world_bible and req.predefined_world_bible.strip():
                    run_input["world_bible_context"] = req.predefined_world_bible
                if req.target_writing_style:
                    run_input["target_writing_style"] = req.target_writing_style
            else:
                # 🌟 场景 B：图处于被挂起的状态
                run_input = None

            # 启动数据流转
            async for chunk in storyweaver_app.astream(run_input,
                                                       config=config,
                                                       stream_mode=["updates", "messages"]):
                mode = chunk[0]
                payload_data = chunk[1]

                if mode == "messages":
                    msg_chunk, metadata = payload_data
                    if metadata.get("langgraph_node") == "Chapter_Writer" and msg_chunk.content:
                        payload = {"type": "chunk", "content": msg_chunk.content}
                        yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

                elif mode == "updates":
                    node_name = list(payload_data.keys())[0]
                    state_updates = payload_data[node_name]
                    safe_updates = {k: v for k, v in state_updates.items() if k != "messages"}
                    payload = {"node": node_name, "updates": safe_updates}
                    yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

            # 探测断点位置并给前端发送挂起信号
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
async def receive_human_feedback(req: FeedbackRequest, request: Request):  # 🌟 添加 request 依赖
    graph_thread_id = req.thread_id
    config = {"configurable": {"thread_id": graph_thread_id}}

    # 🌟 核心修改：直接从全局获取记忆池
    memory = request.app.state.checkpoint_saver

    try:
        # 🌟 核心修改：去掉了 async with 块，下面的代码整体向左缩进一层
        storyweaver_app = request.app.state.storyweaver_app

        current_state = await storyweaver_app.aget_state(config)
        if not current_state.next:
            raise HTTPException(status_code=400, detail="当前没有被挂起的任务。")

        if req.target_node == "Chapter_Writer" and "Chapter_Writer" in current_state.next:
            await storyweaver_app.aupdate_state(config, {"current_beat_sheet": req.edited_beat_sheet})
            return {"status": "success", "message": "大纲已确认，准备流式生成正文。"}

        elif req.target_node == "Human_Review" and "Human_Review" in current_state.next:
            human_decision = {
                "human_approval_status": req.approval_status,
                "human_feedback": req.human_feedback,
                "direct_edits": req.direct_edits
            }

            await storyweaver_app.aupdate_state(config, human_decision)

            if req.approval_status == "APPROVED":
                async for _ in storyweaver_app.astream(None, config=config, stream_mode="updates"):
                    pass
            else:
                async for event in storyweaver_app.astream(None, config=config, stream_mode="updates"):
                    if "Human_Review" not in event:
                        break
            return {"status": "success", "message": "正文反馈已接收，已同步至状态机。",
                    "approval": req.approval_status}

        else:
            raise HTTPException(status_code=400, detail="目标节点与当前挂起状态不匹配。")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"唤醒执行失败: {str(e)}")


@router.get("/books")
async def list_books():
    if not os.path.exists(settings.DATA_DIR):
        return {"books": []}

    books = []
    for item in os.listdir(settings.DATA_DIR):
        item_path = os.path.join(settings.DATA_DIR, item)
        if os.path.isdir(item_path) and item not in ["references", "raw_drafts"]:
            books.append(item)
    return {"books": books}


@router.delete("/books/{book_id}")
async def delete_book(book_id: str):
    book_dir = os.path.join(settings.DATA_DIR, book_id)
    if os.path.exists(book_dir):
        try:
            shutil.rmtree(book_dir, ignore_errors=True)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"文件清理失败: {str(e)}")

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM checkpoints WHERE thread_id = ?", (book_id,))
            await db.execute("DELETE FROM checkpoint_writes WHERE thread_id = ?", (book_id,))
            await db.execute("DELETE FROM checkpoint_blobs WHERE thread_id = ?", (book_id,))
            await db.commit()
    except Exception as e:
        print(f"⚠️ SQLite 清理遇到阻碍: {e}")

    return {"status": "success", "message": f"书籍 {book_id} 已被彻底超度。"}