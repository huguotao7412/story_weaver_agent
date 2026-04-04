# 定义 /novel/stream (流式生成) 与 /novel/feedback (接收总编意见)
# app/api/routes.py

import os
import json
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

class StyleRequest(BaseModel):
    reference_text: str


class FeedbackRequest(BaseModel):
    thread_id: str = "story_thread_01"
    approval_status: Literal["APPROVED", "REJECTED"]
    human_feedback: Optional[str] = ""
    direct_edits: Optional[str] = ""

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
        "current_chapter_num": req.chapter_num
    }

    if req.target_writing_style:
        initial_state["target_writing_style"] = req.target_writing_style

    async def event_generator():
        try:
            # 🌟 在请求内动态创建异步 DB 连接
            async with AsyncSqliteSaver.from_conn_string(DB_PATH) as memory:
                workflow = build_workflow()
                storyweaver_app = workflow.compile(
                    checkpointer=memory,
                    interrupt_before=["Human_Review"]
                )

                # 🌟 使用 .astream() 获取异步流转事件
                async for event in storyweaver_app.astream(initial_state, config=config):
                    node_name = list(event.keys())[0]
                    state_updates = event[node_name]

                    payload = {
                        "node": node_name,
                        "updates": state_updates
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

                yield "data: {\"status\": \"PAUSED_FOR_HUMAN_REVIEW\"}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# === 核心接口 2：接收人类总编反馈并唤醒 (异步升级版) ===
@router.post("/feedback")
async def receive_human_feedback(req: FeedbackRequest):
    config = {"configurable": {"thread_id": req.thread_id}}

    try:
        # 🌟 同样在审批接口内建立独立的异步连接
        async with AsyncSqliteSaver.from_conn_string(DB_PATH) as memory:
            workflow = build_workflow()
            storyweaver_app = workflow.compile(
                checkpointer=memory,
                interrupt_before=["Human_Review"]
            )

            # 🌟 全部替换为带 'a' 前缀的异步方法：aget_state
            current_state = await storyweaver_app.aget_state(config)
            if not current_state or "Human_Review" not in current_state.next:
                raise HTTPException(
                    status_code=400,
                    detail="当前没有等待人类审核的草稿。请先调用 /stream 生成草稿。"
                )

            human_decision = {
                "human_approval_status": req.approval_status,
                "human_feedback": req.human_feedback,
                "direct_edits": req.direct_edits
            }
            # 🌟 异步更新状态：aupdate_state
            await storyweaver_app.aupdate_state(config, human_decision)

            # 🌟 异步执行后续节点：ainvoke
            await storyweaver_app.ainvoke(None, config=config)

            next_step = (await storyweaver_app.aget_state(config)).next
            status_msg = "入库完成" if not next_step else "已打回主笔重写"

            return {
                "status": "success",
                "message": f"反馈已接收，{status_msg}。",
                "approval": req.approval_status
            }

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"唤醒执行失败: {str(e)}")