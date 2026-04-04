# 智能体间通信协议 (大纲结构、文风白皮书格式校验)
# protocols/a2a_schemas.py
from pydantic import BaseModel, Field
from typing import List

class StyleGuide(BaseModel):
    """🎭 文风白皮书协议：Style-Analyzer 提取并传递给全图"""
    tone: str = Field(description="整体基调，例如：轻松、沉重、冷血、极快节奏")
    sentence_structure: str = Field(description="句式特征，例如：大量短句、感叹号丰富")
    vocabulary: str = Field(description="用词偏好，例如：通俗大白话、下沉市场网络梗")
    action_dialogue_ratio: str = Field(description="动静比（对话与动作描写的比例）")
    compiled_prompt: str = Field(description="提炼出的供主笔直接使用的系统级 Prompt")

class BeatSheetNode(BaseModel):
    """网文节拍器（单章内的剧情微节点）"""
    plot_summary: str = Field(description="本段剧情的核心摘要")
    is_climax: bool = Field(default=False, description="当前节拍是否包含【打脸/爽点】")
    hook: str = Field(default="", description="如果位于结尾，这里填写【悬念钩子】的具体设计")

class ChapterOutline(BaseModel):
    """🗺️ 单章大纲协议：Plot-Planner 传递给 Chapter-Writer"""
    chapter_number: int = Field(description="章节序号")
    chapter_title: str = Field(description="章节标题")
    beats: List[BeatSheetNode] = Field(description="拆解出来的单章节拍器列表")
    mandatory_elements: List[str] = Field(description="本章必须涉及的核心世界观元素或人物状态更迭")

class ChapterSummary(BaseModel):
    """单章剧情核心摘要 (用于分卷大纲)"""
    chapter_number: int = Field(description="预期章节号")
    core_conflict: str = Field(description="本章的核心冲突、看点或主线推进任务")

class VolumeOutline(BaseModel):
    """🗺️ 宏观分卷大纲协议：Macro-Planner 规划整个卷 (约10-30章) 的脉络"""
    volume_name: str = Field(description="本卷名称，例如：坊市风云、初入秘境")
    volume_goal: str = Field(description="主角在本卷要达成的最终核心目标")
    chapter_summaries: List[ChapterSummary] = Field(description="本卷内的各章核心剧情梗概列表")