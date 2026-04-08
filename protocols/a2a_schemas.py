# protocols/a2a_schemas.py
from pydantic import BaseModel, Field
from typing import List, Literal

class StyleGuide(BaseModel):
    """🎭 文风白皮书协议：Style-Analyzer 提取并传递给全图"""
    tone: str = Field(description="整体基调，例如：轻松、沉重、冷血、极快节奏")
    sentence_structure: str = Field(description="句式特征，例如：大量短句、感叹号丰富")
    vocabulary: str = Field(description="用词偏好，例如：通俗大白话、下沉市场网络梗")
    action_dialogue_ratio: str = Field(description="动静比（对话与动作描写的比例）")
    compiled_prompt: str = Field(description="提炼出的供主笔直接使用的系统级 Prompt")
    example_snippets: List[str] = Field(
        default_factory=list,
        description="从原文中摘录的1-2段最具代表性的原汁原味片段（如极其爽快的打脸白描、对话拉扯），作为 Few-shot 样例"
    )

# ==========================================
# 🌟 百万字长篇：四层大纲协议定义
# ==========================================

class VolumeSummary(BaseModel):
    """单卷摘要 (用于全书总纲)"""
    volume_number: int = Field(description="卷号，例如：1, 2, 3")
    volume_name: str = Field(description="本卷名称，例如：坊市风云、血色秘境")
    core_goal: str = Field(description="主角在本卷要达成的核心目标或核心冲突")

class BookOutline(BaseModel):
    """🗺️ 第一层：全书总纲协议 (10卷)"""
    world_lore: str = Field(description="《世界观风土人情》，包含历史背景、地理环境、势力分布等宏观设定")
    power_system_rules: str = Field(description="《境界战力铁律》，【极其重要】必须严格列出完整的境界等级划分、战力天花板、以及不可轻易就出现越级秒杀的规则")
    volumes: List[VolumeSummary] = Field(description="规划出的10个分卷大纲列表")

class PhaseDetail(BaseModel):
    """单期详情 (十期之一)"""
    phase_name: str = Field(description="时期名称，例如：第1期-潜龙在渊，第5期-腰部高潮")
    plot_mission: str = Field(description="本期的核心剧情任务和转折点")

class VolumePhases(BaseModel):
    """🗺️ 第二层：分卷五期协议"""
    current_volume_name: str = Field(description="当前正在拆解的卷名")
    phases: List[PhaseDetail] = Field(description="包含 5 期的详细任务拆解")

class ChapterSummary(BaseModel):
    """单章剧情核心摘要"""
    chapter_number: int = Field(description="预期章节号")
    core_conflict: str = Field(description="本章的核心冲突、看点或主线推进任务")
    tension_level: str = Field(description="本章的情绪节奏标签，必须是: Low(舒缓/日常), Medium(蓄力/探索), High(爆发/高潮)")

class PhaseChapters(BaseModel):
    """🗺️ 第三层：单期十章协议"""
    target_phase: str = Field(description="当前正在拆解的时期 (如：卷一 前期)")
    chapter_summaries: List[ChapterSummary] = Field(description="本期内约 10 章的核心剧情梗概列表")

# === 第四层：保持原有的节拍器定义 ===
class BeatSheetNode(BaseModel):
    """网文节拍器（单章内的剧情微节点）"""
    plot_summary: str = Field(description="本段剧情的核心摘要")
    is_climax: bool = Field(default=False, description="当前节拍是否包含【打脸/爽点】")
    hook: str = Field(default="", description="如果位于结尾，这里填写【悬念钩子】的具体设计")
    word_count_weight: str = Field(default="15%",description="该节拍在全文的字数占比权重（如：10%, 40%），指示主笔哪些部分需要详写注水，哪些部分一笔带过")

class ChapterOutline(BaseModel):
    """🗺️ 第四层：单章节拍协议"""
    chapter_number: int = Field(description="章节序号")
    chapter_title: str = Field(description="章节标题")
    beats: List[BeatSheetNode] = Field(description="拆解出来的单章节拍器列表")
    mandatory_elements: List[str] = Field(description="本章必须涉及的核心世界观元素或人物状态更迭")
