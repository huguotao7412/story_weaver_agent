# app/agents/workers/all_planner.py
"""Shared helper functions for the planner family of agents.
The individual node implementations have been moved to:
- app/agents/book_planner.py
- app/agents/volume_planner.py
- app/agents/phase_planner.py
- app/agents/chapter_planner.py
"""

import json


def get_focused_volume_phases(volume_phases_json: str, current_chapter_num: int) -> str:
    """
    视野聚焦引擎：将十期大纲折叠，只暴露【当前期】、【下一期(过渡)】和【最终期(终局目标)】。
    防止大模型因信息过载而乱带节奏或提前剧透。
    """
    if not volume_phases_json or volume_phases_json == "（暂无分卷大纲）":
        return volume_phases_json

    try:
        parsed_data = json.loads(volume_phases_json)
        if isinstance(parsed_data, dict) and "phases" in parsed_data:
            phases = parsed_data["phases"]
            data = parsed_data
        elif isinstance(parsed_data, list):
            phases = parsed_data
            data = {"phases": parsed_data}
        else:
            return volume_phases_json

        if not phases or len(phases) <= 3:
            return volume_phases_json

        current_phase_idx = ((current_chapter_num - 1) % 50) // 10
        last_phase_idx = len(phases) - 1

        focused_phases = []
        for i, phase in enumerate(phases):
            if i == current_phase_idx or i == current_phase_idx + 1 or i == last_phase_idx:
                focused_phases.append(phase)
            elif i == current_phase_idx + 2 and i < last_phase_idx:
                focused_phases.append({
                    "phase_name": "中间期 (已折叠)",
                    "plot_mission": "【系统已折叠无关的未来剧情，避免剧透，请主笔绝对专注眼前的任务！】"
                })

        data["phases"] = focused_phases
        return json.dumps(data, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"⚠️ [Volume-Filter] 折叠大纲失败: {e}", flush=True)
        return volume_phases_json


def get_focused_phase_chapters(phase_chapters_json: str, current_chapter_num: int) -> str:
    """
    单期大纲视野遮罩：只向大模型暴露【上一章(接续)】【本章(核心)】【下一章(悬念目标)】。
    彻底抹除未来剧情，防止底层节拍器抢跑。
    """
    if not phase_chapters_json or phase_chapters_json == "（暂无期大纲）":
        return phase_chapters_json

    try:
        parsed_data = json.loads(phase_chapters_json)
        if isinstance(parsed_data, dict) and "chapter_summaries" in parsed_data:
            summaries = parsed_data["chapter_summaries"]
            data = parsed_data
        elif isinstance(parsed_data, list):
            summaries = parsed_data
            data = {"chapter_summaries": parsed_data}
        else:
            return phase_chapters_json

        if not summaries:
            return phase_chapters_json

        current_idx = (current_chapter_num - 1) % 10

        focused_summaries = []
        for i, chapter in enumerate(summaries):
            if current_idx > 0 and i == current_idx - 1:
                chapter["_system_note"] = "【上一章已发生剧情】请确保本章的第一个节拍与此无缝接续。"
                focused_summaries.append(chapter)
            elif i == current_idx:
                chapter["_system_note"] = "🔥🔥🔥【本章核心任务】你的所有节拍必须且只能推进到这里！绝不允许越界！"
                focused_summaries.append(chapter)
            elif i == current_idx + 1:
                chapter["_system_note"] = "🛑【下一章预告】仅供结尾悬念铺垫参考。绝对禁止在本章的节拍中提前写出这里的剧情！"
                focused_summaries.append(chapter)
            else:
                focused_summaries.append({
                    "chapter_number": chapter.get("chapter_number"),
                    "core_conflict": "【已隐藏的未来或过去剧情，绝对禁止触碰】"
                })

        data["chapter_summaries"] = focused_summaries
        return json.dumps(data, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"⚠️ [Phase-Filter] 大纲切片失败: {e}", flush=True)
        return phase_chapters_json
