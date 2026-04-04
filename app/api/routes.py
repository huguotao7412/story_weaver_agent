# 定义 /novel/stream (流式生成) 与 /novel/feedback (接收总编意见)
# app/api/routes.py

import json
from typing import Optional, Literal,Dict, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from app.agents.workers.style_analyzer import style_analyzer_node
from app.agents.graph import storyweaver_app

router = APIRouter(prefix="/novel", tags=["Novel Workflow"])


# === 数据模型定义 ===
class GenerateRequest(BaseModel):
    user_input: str
    thread_id: str = "story_thread_01"  # 用于区分不同用户的会话或不同小说的进程
    chapter_num: int = 1
    target_writing_style: Optional[Dict[str, Any]] = None

class StyleRequest(BaseModel):
    reference_text: str  # 接收参考文本


class FeedbackRequest(BaseModel):
    thread_id: str = "story_thread_01"
    approval_status: Literal["APPROVED", "REJECTED"]
    human_feedback: Optional[str] = ""
    direct_edits: Optional[str] = ""

# === 🌟 新增接口：独立触发文风解构师 ===
@router.post("/analyze_style")
async def analyze_style_api(req: StyleRequest):
    """提取参考神作的文风特征，生成文风白皮书"""
    try:
        # 模拟图状态，单独调用文风解构师节点
        state_mock = {"messages": [HumanMessage(content=req.reference_text)]}
        result = style_analyzer_node(state_mock)
        return {"status": "success", "style_guide": result.get("target_writing_style", {})}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文风提取失败: {str(e)}")

# === 核心接口 1：流式启动节点 ===
@router.post("/stream")
async def generate_novel_stream(req: GenerateRequest):
    """
    启动或推进小说生成图，流式返回各节点的执行状态。
    当图执行到 Human_Review 前时，会自动挂起并停止流输出。
    """
    config = {"configurable": {"thread_id": req.thread_id}}

    # 构造初始输入状态
    initial_state = {
        "messages": [HumanMessage(content=req.user_input)],
        "current_chapter_num": req.chapter_num
    }

    if req.target_writing_style:
        initial_state["target_writing_style"] = req.target_writing_style

    async def event_generator():
        try:
            # 使用 .stream() 获取图的流转事件
            # 在图被 interrupt_before=["Human_Review"] 挂起时，循环会自动结束
            for event in storyweaver_app.stream(initial_state, config=config):
                # event 是一个字典，格式如 {"Plot_Planner": {"current_beat_sheet": "..."}}
                node_name = list(event.keys())[0]
                state_updates = event[node_name]

                # 推送节点状态变更
                payload = {
                    "node": node_name,
                    "updates": state_updates
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            yield "data: {\"status\": \"PAUSED_FOR_HUMAN_REVIEW\"}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# === 核心接口 2：接收人类总编反馈并唤醒 ===
@router.post("/feedback")
async def receive_human_feedback(req: FeedbackRequest):
    """
    接收人类总编的审批结果（批准/打回），注入 State 并重新唤醒挂起的图。
    """
    config = {"configurable": {"thread_id": req.thread_id}}

    # 1. 检查当前图是否真的处于挂起状态
    current_state = storyweaver_app.get_state(config)
    if not current_state or "Human_Review" not in current_state.next:
        raise HTTPException(
            status_code=400,
            detail="当前没有等待人类审核的草稿。请先调用 /stream 生成草稿。"
        )

    # 2. 将人类的决策作为强制状态注入（Human Override）
    human_decision = {
        "human_approval_status": req.approval_status,
        "human_feedback": req.human_feedback,
        "direct_edits": req.direct_edits
    }
    storyweaver_app.update_state(config, human_decision)

    # 3. 唤醒图执行：传入 None 继续跑
    # 这里也可以用 stream 跑，但为了让前端逻辑简单，唤醒后通常只需要知道成功没成功
    try:
        # 如果是 APPROVED，会流转到 Memory_Keeper 然后 END
        # 如果是 REJECTED，会流转到 Chapter_Writer 重新写
        final_state = storyweaver_app.invoke(None, config=config)

        # 判断接下来去了哪里
        next_step = storyweaver_app.get_state(config).next
        status_msg = "入库完成" if not next_step else "已打回主笔重写"

        return {
            "status": "success",
            "message": f"反馈已接收，{status_msg}。",
            "approval": req.approval_status
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"唤醒执行失败: {str(e)}")