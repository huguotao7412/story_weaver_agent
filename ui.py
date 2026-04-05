# ui.py
import os
import streamlit as st
import requests
import json

from app.core.config import settings

API_BASE_URL = "http://127.0.0.1:8000/novel"

st.set_page_config(page_title="StoryWeaver-Agent 总编操作台", page_icon="📖", layout="wide")

# === 初始化 Session State ===
# 🌟 移除随机 UUID，固定一个清晰的新书默认名称
if "thread_id" not in st.session_state: st.session_state.thread_id = "my_new_book_01"
if "target_writing_style" not in st.session_state: st.session_state.target_writing_style = None
if "draft_content" not in st.session_state: st.session_state.draft_content = "暂无草稿..."
if "edited_draft" not in st.session_state: st.session_state.edited_draft = ""
if "current_beat_sheet" not in st.session_state: st.session_state.current_beat_sheet = ""
if "is_paused_for_review" not in st.session_state: st.session_state.is_paused_for_review = False
if "is_paused_for_beat_sheet" not in st.session_state: st.session_state.is_paused_for_beat_sheet = False
if "system_status" not in st.session_state: st.session_state.system_status = "🟢 待机中"
if "editor_comments" not in st.session_state: st.session_state.editor_comments = ""
if "predefined_world_bible" not in st.session_state: st.session_state.predefined_world_bible = ""

# === 侧边栏：建书隔离、世界观注入、文风提取 ===
with st.sidebar:
    # 🌟 新增：多项目隔离机制
    st.header("📂 项目/书目管理")
    st.markdown("通过 ID 彻底隔离每本书的剧情库。输入相同的 ID 即可继续上次的断点续写。")
    new_thread_id = st.text_input("当前项目 (Book ID)", value=st.session_state.thread_id)

    # 切换书籍时自动清空 UI 残留的视觉缓存
    if new_thread_id != st.session_state.thread_id:
        st.session_state.thread_id = new_thread_id
        st.session_state.draft_content = "暂无草稿..."
        st.session_state.current_beat_sheet = ""
        st.session_state.editor_comments = ""
        st.session_state.is_paused_for_beat_sheet = False
        st.session_state.is_paused_for_review = False
        st.rerun()

    st.divider()

    st.header("🌍 全局世界观基座")
    st.markdown("如果您已有设定好的背景、境界划分、主角金手指，请在此填入。系统将以此为基准推演大纲。")
    st.session_state.predefined_world_bible = st.text_area(
        "预设设定 (选填)",
        value=st.session_state.predefined_world_bible,
        height=200,
        placeholder="例如：本书修仙境界分为练气、筑基、金丹...主角带有一个可以催熟灵草的小瓶子。"
    )

    st.divider()

    st.header("🎭 全局文风克隆引擎")
    st.markdown("上传 `.txt` 神作片段 (1000-3000字)，让 AI 自动解构文风！")
    uploaded_file = st.file_uploader("选择新的参考文本", type=["txt"])
    if uploaded_file is not None:
        ref_content = uploaded_file.read().decode("utf-8")
        try:
            save_path = os.path.join(settings.REFERENCES_DIR, uploaded_file.name)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(ref_content)
            st.success(f"📁 文件已保存: `{uploaded_file.name}`")
        except Exception as e:
            st.error(f"归档失败: {e}")

        if st.button("🧬 立即提取该文风", use_container_width=True, type="primary"):
            with st.spinner("文风解构师正在逐句分析..."):
                try:
                    res = requests.post(f"{API_BASE_URL}/analyze_style", json={"reference_text": ref_content})
                    if res.status_code == 200:
                        st.session_state.target_writing_style = res.json().get("style_guide", {})
                        st.success("✅ 文风白皮书已激活！")
                    else:
                        st.error("提取失败。")
                except Exception as e:
                    st.error(f"网络异常: {e}")

    st.divider()
    st.subheader("📚 本地参考神作库")
    if os.path.exists(settings.REFERENCES_DIR):
        existing_files = [f for f in os.listdir(settings.REFERENCES_DIR) if f.endswith(".txt")]
        if not existing_files:
            st.info("暂无参考文本。")
        else:
            for f_name in existing_files:
                col_name, col_del, col_ext = st.columns([5, 2, 3])
                with col_name:
                    st.markdown(f"📄 `{f_name}`")
                with col_del:
                    if st.button("🗑️", key=f"del_{f_name}"):
                        os.remove(os.path.join(settings.REFERENCES_DIR, f_name))
                        st.rerun()
                with col_ext:
                    if st.button("🧬提取", key=f"ext_{f_name}"):
                        with open(os.path.join(settings.REFERENCES_DIR, f_name), "r", encoding="utf-8") as f:
                            res = requests.post(f"{API_BASE_URL}/analyze_style", json={"reference_text": f.read()})
                            if res.status_code == 200:
                                st.session_state.target_writing_style = res.json().get("style_guide", {})
                                st.success("✅ 激活成功！")

    if st.session_state.target_writing_style:
        with st.expander("🟢 当前文风特征", expanded=True):
            st.json(st.session_state.target_writing_style.get("novel_specific", {}).get("rules", {}))

# ==========================================
# 🌟 UI 骨架与占位符重构
# ==========================================
st.title("📖 StoryWeaver-Agent 总编操作台")
status_ph = st.empty()
status_ph.markdown(
    f"**当前项目 ID**: `{st.session_state.thread_id}` | **系统状态**: {st.session_state.system_status}")
st.divider()

col_left, col_right = st.columns([6, 4])

with col_left:
    st.subheader("📝 事务草稿区")
    tab1, tab2, tab3 = st.tabs(["✍️ 当前正文草稿", "🗺️ 本章节拍器", "🕵️ 内部审查意见"])
    with tab1: draft_ph = st.empty()
    with tab2: beat_ph = st.empty()
    with tab3: editor_ph = st.empty()

if st.session_state.is_paused_for_review:
    edited_draft = draft_ph.text_area("✍️ 终极权限：直接润色文本，通过后将入库", value=st.session_state.draft_content,
                                      height=600)
    st.session_state.edited_draft = edited_draft
else:
    draft_ph.markdown(f"### ✍️ 当前正文\n\n{st.session_state.draft_content}")

beat_ph.markdown(f"### 🗺️ 单章大纲 (JSON)\n\n```json\n{st.session_state.current_beat_sheet}\n```")

with editor_ph.container():
    if st.session_state.editor_comments == "PASS":
        st.success("✅ 逻辑审查通过")
    elif st.session_state.editor_comments:
        st.error(f"❌ 逻辑异常：\n\n{st.session_state.editor_comments}")
    else:
        st.info("等待审查...")


# ==========================================
# 🌟 流式 API 调用与动态渲染
# ==========================================
def start_generation_stream(user_input, chapter_num):
    st.session_state.system_status = "⏳ 引擎流转中..."
    st.session_state.is_paused_for_review = False
    st.session_state.is_paused_for_beat_sheet = False
    status_ph.markdown(f"**当前项目 ID**: `{st.session_state.thread_id}` | **状态**: {st.session_state.system_status}")

    payload = {
        "user_input": user_input,
        "thread_id": st.session_state.thread_id,
        "chapter_num": chapter_num,
        "target_writing_style": st.session_state.target_writing_style,
        "predefined_world_bible": st.session_state.predefined_world_bible
    }

    try:
        with requests.post(f"{API_BASE_URL}/stream", json=payload, stream=True) as response:
            for line in response.iter_lines():
                if line:
                    decoded = line.decode("utf-8")
                    if decoded.startswith("data: "):
                        try:
                            data = json.loads(decoded[6:])

                            if data.get("status") == "PAUSED_FOR_HUMAN_REVIEW":
                                st.session_state.is_paused_for_review = True
                                st.session_state.system_status = "⏸️ 内部审查完毕，等待总编批示正文！"
                                break
                            elif data.get("status") == "PAUSED_FOR_BEAT_SHEET_REVIEW":
                                st.session_state.is_paused_for_beat_sheet = True
                                st.session_state.system_status = "⏸️ 大纲已生成，等待总编确认节拍！"
                                break

                            updates = data.get("updates", {})
                            node_name = data.get("node", "")

                            if "current_beat_sheet" in updates:
                                st.session_state.current_beat_sheet = updates["current_beat_sheet"]
                                beat_ph.markdown(
                                    f"### 🗺️ 大纲生成中...\n\n```json\n{st.session_state.current_beat_sheet}\n```")

                            if "draft_content" in updates:
                                st.session_state.draft_content = updates["draft_content"]
                                draft_ph.markdown(
                                    f"### ✍️ {node_name} 奋笔疾书中...\n\n{st.session_state.draft_content} ▌")

                            if "editor_comments" in updates:
                                st.session_state.editor_comments = updates["editor_comments"]
                                with editor_ph.container():
                                    if st.session_state.editor_comments == "PASS":
                                        st.success("✅ PASS")
                                    elif st.session_state.editor_comments:
                                        st.error(f"❌ 异常：{st.session_state.editor_comments}")
                                    else:
                                        st.info(f"审查中... ({node_name})")
                        except:
                            pass
    except Exception as e:
        st.error(f"异常: {e}")


def send_human_feedback(approval_status, feedback_text):
    original = st.session_state.get("draft_content", "")
    edited = st.session_state.get("edited_draft", "")
    direct_edits = edited if edited and edited != original else ""

    payload = {
        "thread_id": st.session_state.thread_id,
        "approval_status": approval_status,
        "human_feedback": feedback_text,
        "direct_edits": direct_edits,
        "target_node": "Human_Review"
    }

    res = requests.post(f"{API_BASE_URL}/feedback", json=payload)
    if res.status_code == 200:
        st.session_state.is_paused_for_review = False
        if approval_status == "REJECTED":
            start_generation_stream("", st.session_state.get("current_chapter_num", 1))
            st.rerun()
        else:
            st.session_state.system_status = "✅ 章节已批准并入库！"
    else:
        st.error("反馈失败")


# ==========================================
# 👑 右侧控制台 (前置/后置 HITL 分流)
# ==========================================
with col_right:
    st.subheader("👑 创作指令与批注台")

    if st.session_state.is_paused_for_beat_sheet:
        st.warning("⚠️ 第一阶段：本章节拍器(大纲)已出炉！")
        st.info("💡 请确认走向。若不满意，可直接修改下方 JSON，或在此文本框内增加指示要求模型重新生成。")
        edited_beat = st.text_area("修改节拍器大纲：", value=st.session_state.current_beat_sheet, height=300)

        if st.button("✅ 大纲无误，生成 3000 字正文", type="primary", use_container_width=True):
            requests.post(f"{API_BASE_URL}/feedback", json={
                "thread_id": st.session_state.thread_id,
                "approval_status": "APPROVED",
                "target_node": "Chapter_Writer",
                "edited_beat_sheet": edited_beat
            })
            st.session_state.is_paused_for_beat_sheet = False
            start_generation_stream("", st.session_state.get("current_chapter_num", 1))
            st.rerun()

    elif st.session_state.is_paused_for_review:
        st.warning("⚠️ 第二阶段：内部互搏已结束，等待决断。")
        human_feedback = st.text_area("修改批注：", placeholder="例如：主角太软弱，重写结尾。")
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("✅ 批准入库", type="primary", use_container_width=True):
                send_human_feedback("APPROVED", "")
                st.rerun()
        with col_btn2:
            if st.button("🔄 打回重写", use_container_width=True):
                if not human_feedback:
                    st.error("打回必须填写批注！")
                else:
                    send_human_feedback("REJECTED", human_feedback)
                    st.rerun()

    else:
        with st.form("generate_form"):
            st.markdown("**下达生成指令**")
            chapter_input = st.number_input("章节号", min_value=1, value=1, step=1)
            plot_prompt = st.text_area("剧情指令", placeholder="例如：在坊市捡漏买到神秘残片...")
            if st.form_submit_button("🚀 生成本章大纲", use_container_width=True):
                if not plot_prompt:
                    st.warning("请输入指令！")
                else:
                    st.session_state.current_chapter_num = chapter_input
                    start_generation_stream(plot_prompt, chapter_input)
                    st.rerun()