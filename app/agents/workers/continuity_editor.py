# app/agents/workers/continuity_editor.py

from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.core.llm_factory import get_llm
from protocols.hitl_schemas import EditorInternalReview

# ==========================================
# 🕵️ 提示词定义区 (吸收 Consistency Agent 的多维校验技术)
# ==========================================
# 🌟 修改点：移除了原本强行要求输出 JSON 和屏蔽 Markdown 格式的指令，交由 with_structured_output 处理
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
"""


# ==========================================
# 🚀 核心节点逻辑
# ==========================================
async def continuity_editor_node(state: dict) -> Dict[str, Any]:
    """
    🕵️ Continuity-Editor (逻辑审查员)
    职责：采用对比校验技术，拦截草稿中的多维度逻辑 Bug。
    """
    print("🕵️ [Editor] 正在进行多维度一致性排雷审查...")

    draft = state.get("draft_content", "")
    world_bible = state.get("world_bible_context", "暂无世界观数据")
    beat_sheet = state.get("current_beat_sheet", "暂无大纲数据")
    history_context = state.get("rag_history_context", "暂无历史数据")
    current_count = state.get("internal_revision_count", 0)

    # 如果草稿为空（异常情况），直接打回并增加重试计数
    if not draft or draft.strip() == "":
        print("❌ [Editor] 草稿内容为空！")
        return {
            "editor_comments": "FAIL: 草稿内容为空，请主笔重新生成。",
            "internal_revision_count": current_count + 1
        }

    # 逻辑审查需要极强的推理和对比能力，必须使用 main 模型（如 GPT-4o / DeepSeek-Chat）
    llm = get_llm(model_type="main", temperature=0.1)

    # 🌟 核心改造：绑定 Pydantic 模型
    structured_llm = llm.with_structured_output(EditorInternalReview)

    sys_prompt = EDITOR_PROMPT.format(
        world_bible=world_bible,
        history_context=history_context,
        beat_sheet=beat_sheet
    )

    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=f"【主笔提交的草稿】：\n{draft}\n\n请严格按照上述四大维度进行审查。")
    ]

    try:
        # 直接获取验证过的 Pydantic 对象
        review_result: EditorInternalReview =await structured_llm.ainvoke(messages)

        status = review_result.status
        consistency_score = review_result.consistency_score

        # 判断打回条件：status 为 FAIL，或者一致性评分过低
        if status == "PASS" and consistency_score >= 0.8:
            print(f"✅ [Editor] 审查通过！草稿逻辑无懈可击。(一致性评分: {consistency_score})")
            msg = AIMessage(content="[Editor] 逻辑审查通过，准备提交总编。", name="Editor")
            return {
                "editor_comments": "PASS",
                "internal_revision_count": 0,  # 🌟 成功则清零重试计数器
                "messages": [msg]
            }
        else:
            # 🌟 修复点：直接读取对象的属性，而不是用 dict 的 get 方法
            bugs_list = review_result.bug_reports
            bugs = "\n".join([f"- {bug}" for bug in bugs_list]) if bugs_list else "- 发现未知的一致性异常。"
            suggestions = review_result.revision_suggestions or "无明确建议，请对照大纲自行检查。"

            final_comments = f"【审查未通过】(一致性评分: {consistency_score})\n【Bug列表】:\n{bugs}\n\n【修改建议】:\n{suggestions}"
            msg = AIMessage(content=final_comments, name="Editor")

            return {
                "editor_comments": final_comments,
                "internal_revision_count": current_count + 1,  # 🌟 失败则将计数器 +1，避免死循环
                "messages": [msg]
            }

    except Exception as e:
        print(f"⚠️ [Editor] 结构化输出或审查过程发生未知错误: {e}")
        # 兜底：如果模型出错，依然累加计数，防止一直死循环报错
        return {
            "editor_comments": f"FAIL: 逻辑审查员系统异常 ({e})，请主笔重新排版并生成一次草稿。",
            "internal_revision_count": current_count + 1
        }