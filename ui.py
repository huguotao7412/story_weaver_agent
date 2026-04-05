# ui.py
import os
import streamlit as st
import requests
import json

from app.core.config import settings

API_BASE_URL = "http://127.0.0.1:8000/novel"

st.set_page_config(page_title="StoryWeaver-Agent 总编操作台", page_icon="📖", layout="wide")


# === 🌟 进度探针函数 ===
def fetch_book_progress(book_id):
    try:
        res = requests.get(f"{API_BASE_URL}/books/{book_id}/progress")
        if res.status_code == 200:
            return res.json().get("next_chapter", 1)
    except:
        pass
    return 1


# === 初始化 Session State ===
if "thread_id" not in st.session_state: st.session_state.thread_id = "my_new_book_01"
if "current_chapter_num" not in st.session_state: st.session_state.current_chapter_num = fetch_book_progress(
    st.session_state.thread_id)
if "target_writing_style" not in st.session_state: st.session_state.target_writing_style = None
if "draft_content" not in st.session_state: st.session_state.draft_content = "暂无草稿..."
if "current_beat_sheet" not in st.session_state: st.session_state.current_beat_sheet = ""
if "predefined_world_bible" not in st.session_state: st.session_state.predefined_world_bible = ""
if "plot_prompt_input" not in st.session_state: st.session_state.plot_prompt_input = ""
if "show_success_effect" not in st.session_state: st.session_state.show_success_effect = False

# 🌟 严密状态机: IDLE (待机), RUNNING (推演中), REVIEW_BEAT (审大纲), REVIEW_DRAFT (审草稿)
if "app_stage" not in st.session_state: st.session_state.app_stage = "IDLE"

# ==========================================
# 侧边栏：建书隔离、世界观、文风提取
# ==========================================
with st.sidebar:
    st.header("📂 书库管理中心")

    @st.cache_data(ttl=2)
    def fetch_books():
        try:
            res = requests.get(f"{API_BASE_URL}/books")
            if res.status_code == 200: return res.json().get("books", [])
        except:
            return []
        return []

    existing_books = fetch_books()
    if st.session_state.thread_id not in existing_books: existing_books.append(st.session_state.thread_id)

    current_index = existing_books.index(st.session_state.thread_id)
    selected_book = st.selectbox("📚 选择并切换书目", existing_books, index=current_index)

    if selected_book != st.session_state.thread_id:
        st.session_state.thread_id = selected_book
        st.session_state.current_chapter_num = fetch_book_progress(selected_book)
        st.session_state.draft_content = "暂无草稿..."
        st.session_state.current_beat_sheet = ""
        st.session_state.app_stage = "IDLE"
        st.rerun()

    col_btn_add, col_btn_del = st.columns(2)
    with col_btn_add:
        @st.dialog("➕ 创建新书")
        def create_new_book_dialog():
            new_book_name = st.text_input("输入新书的 Book ID (请使用英文/拼音/数字)")
            if st.button("进入新项目", use_container_width=True, type="primary"):
                if new_book_name and new_book_name.strip():
                    st.session_state.thread_id = new_book_name.strip()
                    st.session_state.current_chapter_num = 1
                    st.session_state.draft_content = "暂无草稿..."
                    st.session_state.current_beat_sheet = ""
                    st.session_state.app_stage = "IDLE"
                    st.rerun()

        if st.button("➕ 新建小说"): create_new_book_dialog()

    with col_btn_del:
        if st.button("🗑️ 销毁本书"):
            try:
                res = requests.delete(f"{API_BASE_URL}/books/{st.session_state.thread_id}")
                if res.status_code == 200:
                    st.success("书籍已销毁！")
                    st.session_state.app_stage = "IDLE"
                    st.rerun()
            except Exception as e:
                st.error(f"销毁失败: {e}")

    st.divider()
    st.header("🌍 全局世界观基座")
    st.session_state.predefined_world_bible = st.text_area(
        "预设设定 (选填)", value=st.session_state.predefined_world_bible, height=150
    )

    st.divider()
    st.header("🎭 全局文风克隆引擎")

    @st.cache_data(ttl=2)
    def fetch_references():
        try:
            res = requests.get(f"{API_BASE_URL}/references")
            if res.status_code == 200: return res.json().get("files", [])
        except:
            return []
        return []

    existing_refs = fetch_references()
    ref_tab1, ref_tab2 = st.tabs(["📁 历史神作库", "⬆️ 上传新文本"])

    selected_ref = None
    uploaded_ref_content = None

    with ref_tab1:
        if existing_refs:
            selected_ref = st.selectbox("选择要复用的历史神作", ["-- 请选择 --"] + existing_refs)
        else:
            st.info("暂无历史神作，请前往右侧上传。")
            selected_ref = "-- 请选择 --"

    with ref_tab2:
        uploaded_file = st.file_uploader("选择新的参考文本", type=["txt"])
        if uploaded_file is not None:
            uploaded_ref_content = uploaded_file.read().decode("utf-8")
            try:
                save_path = os.path.join(settings.REFERENCES_DIR, uploaded_file.name)
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(uploaded_ref_content)
                st.success(f"📁 已自动沉淀: `{uploaded_file.name}`")
                fetch_references.clear()
            except Exception as e:
                st.error(f"归档失败: {e}")

    if st.button("🧬 立即提取该文风", use_container_width=True, type="primary"):
        payload = {}
        if uploaded_file is not None:
            payload = {"reference_text": uploaded_ref_content}
        elif selected_ref and selected_ref != "-- 请选择 --":
            payload = {"reference_filename": selected_ref}
        else:
            st.warning("请选择或上传文本！")
            st.stop()

        with st.spinner("正在解构..."):
            try:
                res = requests.post(f"{API_BASE_URL}/analyze_style", json=payload)
                if res.status_code == 200:
                    st.session_state.target_writing_style = res.json().get("style_guide", {})
                    st.success("✅ 文风白皮书已激活！")
            except Exception as e:
                st.error(f"网络异常: {e}")

    if st.session_state.target_writing_style:
        with st.expander("🟢 当前文风特征", expanded=False):
            st.json(st.session_state.target_writing_style.get("novel_specific", {}).get("rules", {}))


# ==========================================
# 🌟 流式 API 调用与反馈机制
# ==========================================
def start_generation_stream(user_input, chapter_num):
    st.session_state.app_stage = "RUNNING"
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

                            if "error" in data:
                                st.error(f"后端执行报错: {data['error']}")
                                break

                            # 正常收到挂起信号
                            if data.get("status") == "PAUSED_FOR_BEAT_SHEET_REVIEW":
                                st.session_state.app_stage = "REVIEW_BEAT"
                                break
                            elif data.get("status") == "PAUSED_FOR_HUMAN_REVIEW":
                                st.session_state.app_stage = "REVIEW_DRAFT"
                                break

                            updates = data.get("updates", {})
                            if "current_beat_sheet" in updates:
                                st.session_state.current_beat_sheet = updates["current_beat_sheet"]
                            if "draft_content" in updates:
                                st.session_state.draft_content = updates["draft_content"]
                        except Exception:
                            pass
    except Exception as e:
        st.error(f"引擎通信异常: {e}")

    if st.session_state.app_stage == "RUNNING":
        if st.session_state.draft_content and st.session_state.draft_content != "暂无草稿...":
            st.session_state.app_stage = "REVIEW_DRAFT"
        elif st.session_state.current_beat_sheet:
            st.session_state.app_stage = "REVIEW_BEAT"
        else:
            st.session_state.app_stage = "IDLE"


def send_beat_feedback(edited_beat, reject=False):
    if reject:
        st.session_state.app_stage = "IDLE"
        st.session_state.current_beat_sheet = ""
        return

    # 🌟 修复：发送反馈时传入当前章节号，配合后端的唤醒定位
    payload = {
        "thread_id": st.session_state.thread_id,
        "chapter_num": st.session_state.current_chapter_num,
        "approval_status": "APPROVED",
        "edited_beat_sheet": edited_beat,
        "target_node": "Chapter_Writer"
    }
    requests.post(f"{API_BASE_URL}/feedback", json=payload)
    start_generation_stream("", st.session_state.current_chapter_num)


def send_draft_feedback(approval_status, feedback_text, direct_edits):
    # 🌟 修复：发送反馈时传入当前章节号，配合后端的唤醒定位
    payload = {
        "thread_id": st.session_state.thread_id,
        "chapter_num": st.session_state.current_chapter_num,
        "approval_status": approval_status,
        "human_feedback": feedback_text,
        "direct_edits": direct_edits,
        "target_node": "Human_Review"
    }
    res = requests.post(f"{API_BASE_URL}/feedback", json=payload)

    if res.status_code == 200:
        if approval_status == "REJECTED":
            start_generation_stream("", st.session_state.current_chapter_num)
        else:
            st.session_state.app_stage = "IDLE"
            st.session_state.current_chapter_num += 1
            st.session_state.plot_prompt_input = ""
            st.session_state.draft_content = "暂无草稿..."
            st.session_state.current_beat_sheet = ""
            st.session_state.show_success_effect = True
    else:
        st.error("反馈提交失败，请检查后端日志。")


# ==========================================
# 🌟 核心工作区
# ==========================================
st.title("📖 StoryWeaver-Agent 总编操作台")

if st.session_state.show_success_effect:
    st.balloons()
    st.success(f"🎉 恭喜！上一章已成功入库。引擎已切换至第 {st.session_state.current_chapter_num} 章，请下达新指令！")
    st.session_state.show_success_effect = False

STATUS_MESSAGES = {
    "IDLE": "🟢 待机中：请下达剧情指令",
    "RUNNING": "⏳ 引擎轰鸣中：多智能体正在疯狂输出，请稍候...",
    "REVIEW_BEAT": "⏸️ 等待决策：大纲已生成，请在下方修改并放行",
    "REVIEW_DRAFT": "⏸️ 等待决策：草稿已生成，请在下方润色并入库"
}
st.markdown(
    f"**当前项目**: `{st.session_state.thread_id}` | "
    f"**目标章节**: 🚀 第 `{st.session_state.current_chapter_num}` 章 | "
    f"**状态**: {STATUS_MESSAGES[st.session_state.app_stage]}"
)
st.divider()

if st.session_state.app_stage == "IDLE":
    with st.container(border=True):
        st.subheader("💡 连载发车中心")
        col_inp1, col_inp2 = st.columns([2, 8])
        with col_inp1:
            chapter_input = st.number_input("当前目标章节号", min_value=1, value=st.session_state.current_chapter_num,
                                            step=1)
        with col_inp2:
            plot_prompt = st.text_input(
                f"为 第 {st.session_state.current_chapter_num} 章 注入剧情脑洞：",
                placeholder="例如：在坊市捡漏买到神秘残片，遇到反派刁难...",
                key="plot_prompt_input"
            )

        if st.button("🚀 启动推演：生成本章大纲", use_container_width=True, type="primary"):
            if not st.session_state.plot_prompt_input:
                st.warning("请输入指令！")
            else:
                st.session_state.current_chapter_num = chapter_input
                start_generation_stream(st.session_state.plot_prompt_input, chapter_input)
                st.rerun()
    st.divider()

# 📝 核心视图：大纲与草稿 Tabs
tab_beat, tab_draft = st.tabs(["🗺️ 大纲/节拍器操作区", "✍️ 正文草稿操作区"])

with tab_beat:
    st.markdown("### 🗺️ 单章大纲 (JSON)")
    if st.session_state.app_stage == "REVIEW_BEAT":
        st.warning("⚠️ 引擎挂起：本章节拍器(大纲)已出炉。你可以直接修改下方文本框内的设定。")
        edited_beat = st.text_area("✍️ 确认与修改大纲：", value=st.session_state.current_beat_sheet, height=300,
                                   key="user_edited_beat")

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            if st.button("✅ 大纲确认，投入算力生成正文", type="primary", use_container_width=True):
                send_beat_feedback(st.session_state.user_edited_beat, reject=False)
                st.rerun()
        with col_b2:
            if st.button("🔄 打回重新生成大纲", use_container_width=True):
                send_beat_feedback("", reject=True)
                st.rerun()
    else:
        if st.session_state.current_beat_sheet:
            st.markdown(f"```json\n{st.session_state.current_beat_sheet}\n```")
        else:
            st.info("暂无大纲，请在发车中心下达指令等待生成。")

with tab_draft:
    st.markdown("### ✍️ 当前正文草稿")
    if st.session_state.app_stage == "REVIEW_DRAFT":
        st.warning("⚠️ 引擎挂起：正文草稿已生成，等待总编润色或打回。")
        edited_draft = st.text_area("✍️ 人工深度润色/修改草稿（所见即所得）：", value=st.session_state.draft_content,
                                    height=500, key="user_edited_draft")
        human_feedback = st.text_area("📝 填写打回批注（仅在打回时需要）：", placeholder="例如：打斗场面太简略，重写。",
                                      key="user_feedback_draft")

        col_d1, col_d2 = st.columns(2)
        with col_d1:
            if st.button("✅ 润色完毕，批准入库", type="primary", use_container_width=True):
                send_draft_feedback("APPROVED", "", st.session_state.user_edited_draft)
                st.rerun()
        with col_d2:
            if st.button("🔄 人类总编批注：打回重写", use_container_width=True):
                if not st.session_state.user_feedback_draft:
                    st.error("打回重写必须填写批注指令！")
                else:
                    send_draft_feedback("REJECTED", st.session_state.user_feedback_draft, "")
                    st.rerun()
    else:
        if st.session_state.draft_content and st.session_state.draft_content != "暂无草稿...":
            st.markdown(st.session_state.draft_content)
        else:
            st.info("引擎尚未生成草稿。")