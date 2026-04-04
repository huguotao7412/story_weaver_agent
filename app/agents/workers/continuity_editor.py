#职责：小说界的“找茬专家”。负责内部校验当前草稿是否违反了人物状态或产生逻辑 Bug。# 🕵️ 逻辑审查员：校验一致性，拦截逻辑 Bug
# app/agents/workers/continuity_editor.py

import json
from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm_factory import get_llm

# ==========================================
# 🕵️ 提示词定义区
# ==========================================
EDITOR_PROMPT = """你是一个极其严苛的网文【逻辑审查员】（找茬专家）。
你的任务是对主笔刚刚写出的正文草稿进行一致性与逻辑校验。

【世界观圣经（参考标准）】：
{world_bible}

【本章节拍器大纲（参考标准）】：
{beat_sheet}

【校验规则 - 请逐条比对】：
1. 人设一致性（OOC检查）：主角的行为和说话语气是否符合世界观设定？
2. 战力/金手指逻辑：有没有出现战力崩坏，或者遇到危机时忘记使用已有的关键金手指？
3. 大纲吻合度：草稿有没有漏写大纲（节拍器）中规定的必写元素、爽点或悬念钩子？
4. 网文常识错误：反派是不是降智得太离谱（如无脑挑衅）？动作描写是否出现瞬移等物理Bug？

请严格以 JSON 格式输出校验结果，数据结构必须如下：
{{
    "status": "PASS",  // 如果没有任何逻辑问题，输出 PASS；如果有问题，输出 FAIL
    "bug_reports": [
        "Bug1：大纲中要求主角使用透视眼，但草稿中主角盲猜了物品，违背了金手指设定。",
        "Bug2：反派张三在上一段还在大笑，下一段突然就被打倒了，缺少动作过渡。"
    ],
    "revision_suggestions": "请主笔在第三段加入主角使用透视眼的心理描写，并补充反派被打倒的动作细节。"
}}

注意：如果 status 为 PASS，bug_reports 可以为空数组。不要包含任何 Markdown 标签，只输出合法 JSON。
"""


# ==========================================
# 🚀 核心节点逻辑
# ==========================================
def continuity_editor_node(state: dict) -> Dict[str, Any]:
    """
    🕵️ Continuity-Editor (逻辑审查员)
    职责：内部校验当前草稿是否违反了人物状态或产生逻辑 Bug。
    """
    print("🕵️ [Editor] 正在审查主笔刚交的草稿...")

    draft = state.get("draft_content", "")
    world_bible = state.get("world_bible_context", "")
    beat_sheet = state.get("current_beat_sheet", "")

    # 如果草稿为空（异常情况），直接打回
    if not draft:
        return {"editor_comments": "FAIL: 草稿内容为空，请主笔重新生成。"}

    # 逻辑审查需要极强的推理和对比能力，必须使用 main 模型（如 GPT-4o / DeepSeek-Chat）
    # 🌟 温度设为极低（0.1），剥夺其创造力，强化其寻找 Bug 的理性思维
    llm = get_llm(model_type="main", temperature=0.1)

    sys_prompt = EDITOR_PROMPT.format(
        world_bible=world_bible,
        beat_sheet=beat_sheet
    )

    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=f"【主笔提交的草稿】：\n{draft}\n\n请进行严厉的审查并输出 JSON 报告。")
    ]

    response = llm.invoke(messages)
    content = response.content.strip()

    # 清理 JSON Markdown 标签
    if content.startswith("```json"):
        content = content[7:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    try:
        review_result = json.loads(content)
        status = review_result.get("status", "PASS")

        if status == "PASS" or status == "pass":
            print("✅ [Editor] 审查通过！草稿逻辑无懈可击。")
            return {"editor_comments": "PASS"}
        else:
            bugs_list = review_result.get("bug_reports", [])
            bugs = "\n".join([f"- {bug}" for bug in bugs_list]) if bugs_list else "- 发现未知的逻辑异常。"
            suggestions = review_result.get("revision_suggestions", "无明确建议，请对照大纲自行检查。")

            final_comments = f"【Bug列表】:\n{bugs}\n\n【修改建议】:\n{suggestions}"
            print("❌ [Editor] 发现逻辑漏洞，已打回给主笔返工！")

            # 返回打回意见，这将被传给下一轮的 Chapter-Writer
            return {"editor_comments": final_comments}

    except json.JSONDecodeError:
        print("⚠️ [Editor] JSON 解析失败，为了防止死循环，本次审查默认放行。")
        return {"editor_comments": "PASS"}