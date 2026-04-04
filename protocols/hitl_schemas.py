# 人类在环协议 (定义人类总编打回/通过的数据格式)
# protocols/hitl_schemas.py
from pydantic import BaseModel, Field
from typing import Literal

class EditorInternalReview(BaseModel):
    """🕵️ 内部 AI 逻辑审查协议 (Continuity-Editor 的输出)"""
    status: Literal["PASS", "FAIL"] = Field(description="内部校验状态")
    bug_reports: list[str] = Field(default_factory=list, description="发现的逻辑漏洞、战力崩塌或 OOC 列表")
    revision_suggestions: str = Field(default="", description="给 Chapter-Writer 的返工指导")

class HumanDecision(BaseModel):
    """👑 人类最高权限干预协议 (Human-in-the-Loop)"""
    approval_status: Literal["APPROVED", "REJECTED", "PENDING"] = Field(
        default="PENDING",
        description="事务控制状态：批准入库、打回重写、等待中"
    )
    human_feedback: str = Field(
        default="",
        description="打回重写时的批注意图（最高指令，例如'反派不够嚣张，重写'）"
    )
    direct_edits: str = Field(
        default="",
        description="人类总编直接在草稿上手动修改的终版文本（直接覆盖系统生成）"
    )