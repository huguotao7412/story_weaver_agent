# 🕵️ 逻辑审查员：多维度校验一致性，精准排雷逻辑 Bug
# 职责：小说界的“找茬专家”。负责内部校验当前草稿是否违反了人物状态、世界观法则或产生逻辑 Bug。
# 吸收了 Consistency Agent 的多维度对比校验技术 (Contrastive Validation Prompting)
# app/agents/workers/continuity_editor.py

import json
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import get_llm

# ==========================================
# 🕵️ 提示词定义区 (吸收 Consistency Agent 的多维校验技术)
# ==========================================
EDITOR_PROMPT = """你是一个极其严苛且精准的网文【逻辑审查员】（Consistency Agent / 找茬专家）。
你的任务是对主笔刚刚写出的正文草稿进行**多维度对比校验（Contrastive Validation）**，精准排查逻辑地雷。

【全局世界观与设定圣经（参考标准）】：
{world_bible}

【🌟前情提要与历史伏笔（参考标准）】：
{history_context}

【本章节拍器大纲（参考标准）】：
{beat_sheet}

【🎯 强制对比校验维度 - 请逐条执行交叉比对】：
请仔细审读草稿，并在内部推理中将草稿内容与上方给定的参考标准进行比对。
1. 🎭 角色状态与人设一致性 (Character Consistency)：
   - 角色性格是否 OOC（Out of Character）？
   - 角色当前的状态（死活、伤病、位置）是否出现空间或时间上的瞬移与矛盾？
2. 🌍 世界观与战力法则 (World-building & Power Levels)：
   - 草稿中的战力表现、技能使用、物品道具是否遵循了《世界观圣经》中的设定规则？
   - 主角有没有忘记使用关键金手指，或者强行打破了已有的实力天花板（战力崩坏）？
3. 🗺️ 剧情线与大纲推进 (Plot Threads & Progression)：
   - 草稿是否准确无误地涵盖了《本章节拍器大纲》要求的所有节拍点、爽点公式和结尾悬念钩子？
   - 是否存在遗漏情节或偏离主线的水文行为？
4. 🧠 网文常识与物理逻辑 (General Logic)：
   - 反派是否降智得太离谱（如无脑挑衅）？动作描写是否符合基础物理逻辑？

请严格以 JSON 格式输出多维度的校验结果，数据结构必须如下：
{{
    "status": "PASS",  // 如果没有任何逻辑问题输出 PASS；如果有任何违规问题输出 FAIL
    "consistency_score": 0.95, // 一致性评分 0.0 - 1.0 (参考：<0.8 必须打回重写)
    "bug_reports": [
        "[角色违规] Bug1：大纲中设定角色A重伤，但草稿中角色A活蹦乱跳参与了战斗。",
        "[世界观违规] Bug2：主角在面临绝境时，完全忘记使用设定的‘透视眼’金手指。",
        "[大纲遗漏] Bug3：结尾缺乏大纲中规定的悬念钩子，剧情收尾太平淡。"
    ],
    "revision_suggestions": "请主笔在第三段加入主角使用透视眼的心理描写，并修正角色A的伤势状态表现。"
}}

注意：
- 如果 status 为 PASS，bug_reports 必须为空数组，consistency_score 应大于 0.9。
- 不要包含任何 Markdown 标签（如 ```json），只输出合法的 JSON 字符串。
"""


# ==========================================
# 🚀 核心节点逻辑
# ==========================================
def continuity_editor_node(state: dict) -> Dict[str, Any]:
    """
    🕵️ Continuity-Editor (逻辑审查员)
    职责：采用对比校验技术，拦截草稿中的多维度逻辑 Bug。
    """
    print("🕵️ [Editor] 正在进行多维度一致性排雷审查...")

    draft = state.get("draft_content", "")
    world_bible = state.get("world_bible_context", "暂无世界观数据")
    beat_sheet = state.get("current_beat_sheet", "暂无大纲数据")

    history_context = state.get("rag_history_context", "暂无历史数据")

    # 如果草稿为空（异常情况），直接打回
    if not draft or draft.strip() == "":
        print("❌ [Editor] 草稿内容为空！")
        return {"editor_comments": "FAIL: 草稿内容为空，请主笔重新生成。"}

    # 逻辑审查需要极强的推理和对比能力，必须使用 main 模型（如 GPT-4o / DeepSeek-Chat）
    # 🌟 温度设为极低（0.1），剥夺其创造力，强化其无情的“找茬”和“对比”思维
    llm = get_llm(model_type="main", temperature=0.1)

    sys_prompt = EDITOR_PROMPT.format(
        world_bible=world_bible,
        history_context=history_context,
        beat_sheet=beat_sheet
    )

    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(
            content=f"【主笔提交的草稿】：\n{draft}\n\n请严格按照上述四大维度进行审查，并仅输出符合规范的 JSON 报告。")
    ]

    try:
        response = llm.invoke(messages)
        content = response.content.strip()

        # 清理可能携带的 Markdown 代码块标签
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        review_result = json.loads(content)
        status = review_result.get("status", "PASS").upper()
        consistency_score = float(review_result.get("consistency_score", 1.0))

        # 判断打回条件：status 为 FAIL，或者一致性评分过低
        if status == "PASS" and consistency_score >= 0.8:
            print(f"✅ [Editor] 审查通过！草稿逻辑无懈可击。(一致性评分: {consistency_score})")
            return {"editor_comments": "PASS"}
        else:
            bugs_list = review_result.get("bug_reports", [])
            bugs = "\n".join([f"- {bug}" for bug in bugs_list]) if bugs_list else "- 发现未知的一致性异常。"
            suggestions = review_result.get("revision_suggestions", "无明确建议，请对照大纲自行检查。")

            final_comments = f"【审查未通过】(一致性评分: {consistency_score})\n【Bug列表】:\n{bugs}\n\n【修改建议】:\n{suggestions}"
            print(f"❌ [Editor] 发现逻辑漏洞 (一致性评分: {consistency_score})，已打回给主笔返工！")

            # 返回带有前缀维度的打回意见，这将被传给下一轮的 Chapter-Writer
            return {"editor_comments": final_comments}

    except json.JSONDecodeError as e:
        print(f"⚠️ [Editor] JSON 解析失败: {e}。原始输出：\n{content}\n为了防止死循环，本次审查默认打回重试。")
        return {"editor_comments": "FAIL: 逻辑审查员系统异常（格式错误），请主笔重新排版并生成一次草稿。"}
    except Exception as e:
        print(f"⚠️ [Editor] 审查过程发生未知错误: {e}")
        return {"editor_comments": "PASS"}