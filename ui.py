# ui.py
import os
import streamlit as st
import requests
import json

from app.core.config import settings

API_BASE_URL = "http://127.0.0.1:8000/novel"

st.set_page_config(page_title="StoryWeaver-Agent 总编操作台", page_icon="📖", layout="wide")

# === 初始化 Session State ===
if "thread_id" not in st.session_state: st.session_state.thread_id = "my_new_book_01"
if "target_writing_style" not in st.session_state: st.session_state.target_writing_style = None
if "draft_content" not in st.session_state: st.session_state.draft_content = "暂无草稿..."
if "edited_draft" not in st.session_state: st.session_state.edited_draft = ""
if "current_beat_sheet" not in st.session_state: st.session_state.current_beat_sheet = ""
if "is_paused_for_review" not in st.session_state: st.session_state.is_paused_for_review = False
if "is_paused_for_beat_sheet" not in st.session_state: st.session_state.is_paused_for_beat_sheet = False
if "system_status" not in st.session_state: st.session_state.system_status = "🟢 待机中"
if "predefined_world_bible" not in st.session_state: st.session_state.predefined_world_bible = ""

# === 侧边栏：建书隔离、世界观注入、文风提取 ===
with st.sidebar:
    st.header("📂 书库管理中心 (Workspace)")


    # 1. 向后端请求最新书单
    @st.cache_data(ttl=2)  # 增加微小缓存防止频繁请求
    def fetch_books():
        try:
            res = requests.get(f"{API_BASE_URL}/books")
            if res.status_code == 200:
                return res.json().get("books", [])
        except:
            return []


    existing_books = fetch_books()

    # 🌟【核心修复 1】：防止下拉框被强行顶回旧书！
    # 如果用户新建了一个书名，但后端还没创建物理文件夹
    # 必须强制把这个新书名保留在列表中，否则 Selectbox 会自动跳回第一本旧书
    if st.session_state.thread_id not in existing_books:
        existing_books.append(st.session_state.thread_id)

    # 2. 下拉框选择已有的书
    current_index = existing_books.index(st.session_state.thread_id)
    selected_book = st.selectbox("📚 选择并切换书目", existing_books, index=current_index)

    if selected_book != st.session_state.thread_id:
        st.session_state.thread_id = selected_book
        st.session_state.draft_content = "暂无草稿..."
        st.session_state.current_beat_sheet = ""
        st.session_state.is_paused_for_beat_sheet = False
        st.session_state.is_paused_for_review = False
        st.rerun()

    col_btn_add, col_btn_del = st.columns(2)

    # 3. 新建书籍的弹窗逻辑
    with col_btn_add:
        @st.dialog("➕ 创建新书")
        def create_new_book_dialog():
            st.info("💡 提示：输入书名后，请在右侧下发剧情指令，系统才会真正创建实体存储。")
            new_book_name = st.text_input("输入新书的 Book ID (请使用英文/拼音/数字)")
            if st.button("进入新项目", use_container_width=True, type="primary"):
                if new_book_name and new_book_name.strip():
                    st.session_state.thread_id = new_book_name.strip()
                    st.session_state.draft_content = "暂无草稿..."
                    st.rerun()


        if st.button("➕ 新建小说"):
            create_new_book_dialog()

    # 4. 删除书籍的核弹按钮
    with col_btn_del:
        @st.dialog("⚠️ 危险操作")
        def delete_book_dialog(book_to_delete):
            st.error(f"你正在尝试彻底删除书籍：【{book_to_delete}】")
            st.warning("此操作将物理删除 FAISS 向量库、状态机数据和正文备份，且无法恢复！")
            confirm_text = st.text_input(f"请输入 '{book_to_delete}' 以确认删除")
            if st.button("🗑️ 确认粉碎", use_container_width=True, disabled=confirm_text != book_to_delete):
                with st.spinner("正在抹除记忆与文件..."):
                    try:
                        res = requests.delete(f"{API_BASE_URL}/books/{book_to_delete}")

                        # 🌟【核心修复 2】：接收后端的真实状态，成功才重置界面
                        if res.status_code == 200:
                            fetch_books.clear()  # 清理缓存强制刷新
                            # 智能寻找下一本书作为默认界面，如果都没了再 fallback
                            remaining = [b for b in existing_books if b != book_to_delete]
                            st.session_state.thread_id = remaining[0] if remaining else "default_book"
                            st.session_state.draft_content = "暂无草稿..."
                            st.rerun()
                        else:
                            st.error(f"❌ 删除失败: {res.text}")
                    except Exception as e:
                        st.error(f"❌ 网络异常，无法连接后端: {e}")


        if st.button("🗑️ 销毁本书"):
            delete_book_dialog(st.session_state.thread_id)

    st.divider()

    st.header("🌍 全局世界观基座")
    st.session_state.predefined_world_bible = st.text_area(
        "预设设定 (选填)",
        value=st.session_state.predefined_world_bible,
        height=200,
        placeholder="例如：本书修仙境界分为练气、筑基...主角带有催熟灵草的小瓶子。"
    )

    st.divider()

    st.header("🎭 全局文风克隆引擎")
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
            with st.spinner("正在解构..."):
                try:
                    res = requests.post(f"{API_BASE_URL}/analyze_style", json={"reference_text": ref_content})
                    if res.status_code == 200:
                        st.session_state.target_writing_style = res.json().get("style_guide", {})
                        st.success("✅ 文风白皮书已激活！")
                except Exception as e:
                    st.error(f"网络异常: {e}")

    if st.session_state.target_writing_style:
        with st.expander("🟢 当前文风特征", expanded=True):
            st.json(st.session_state.target_writing_style.get("novel_specific", {}).get("rules", {}))

# ==========================================
# 🌟 UI 骨架与占位符绝对防御插槽
# ==========================================
st.title("📖 StoryWeaver-Agent 总编操作台")
status_ph = st.empty()
status_ph.markdown(
    f"**当前项目 ID**: `{st.session_state.thread_id}` | **系统状态**: {st.session_state.system_status}")
st.divider()

col_left, col_right = st.columns([6, 4])

with col_left:
    st.subheader("📝 事务草稿区")
    tab1, tab2 = st.tabs(["✍️ 当前正文草稿", "🗺️ 本章节拍器"])

    with tab1:
        draft_ph = st.empty()  # 声明一个永恒存在的插槽
        if st.session_state.is_paused_for_review:
            # 当挂起时，往插槽里塞一个 text_area
            st.session_state.edited_draft = draft_ph.text_area(
                "✍️ 终极权限：直接润色文本，通过后将入库",
                value=st.session_state.draft_content,
                height=600
            )
        else:
            # 正常情况，往插槽里塞 Markdown
            draft_ph.markdown(f"### ✍️ 当前正文\n\n{st.session_state.draft_content}")

    with tab2:
        beat_ph = st.empty()
        beat_ph.markdown(f"### 🗺️ 单章大纲 (JSON)\n\n```json\n{st.session_state.current_beat_sheet}\n```")


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
                                st.session_state.system_status = "⏸️ 正文草稿已出炉，等待总编润色并入库！"
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
                        except Exception:
                            pass

        # 流水线跑完（或者 break 跳出）后，如果是挂起状态，强制重绘 UI 以展示 text_area
        if st.session_state.is_paused_for_review or st.session_state.is_paused_for_beat_sheet:
            st.rerun()

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
            # 打回重写，重新激活引擎
            start_generation_stream("", st.session_state.get("current_chapter_num", 1))
            st.rerun()
        else:
            st.session_state.system_status = "✅ 章节已批准并入库！"
    else:
        st.error("反馈提交失败")


# ==========================================
# 👑 右侧控制台 (前置/后置 HITL 分流)
# ==========================================
with col_right:
    st.subheader("👑 创作指令与批注台")

    if st.session_state.is_paused_for_beat_sheet:
        st.warning("⚠️ 第一阶段：本章节拍器(大纲)已出炉！")
        st.info("💡 请确认走向。若不满意，可直接修改下方 JSON，或在此文本框内增加指示要求模型重写。")
        edited_beat = st.text_area("修改节拍器大纲：", value=st.session_state.current_beat_sheet, height=300)

        if st.button("✅ 大纲无误，生成正文", type="primary", use_container_width=True):
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
        st.warning("⚠️ 第二阶段：正文草稿已生成，等待总编决断。")
        st.info("💡 请在左侧直接润色正文，修改完毕后点击下方【批准入库】。若全盘不满意，填写批注打回重写。")
        human_feedback = st.text_area("打回重写批注：", placeholder="例如：主角太软弱，重写结尾。")

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("✅ 批准并入库", type="primary", use_container_width=True):
                send_human_feedback("APPROVED", "")
                st.rerun()
        with col_btn2:
            if st.button("🔄 强行打回重写", use_container_width=True):
                if not human_feedback:
                    st.error("强行打回必须填写修改批注！")
                else:
                    send_human_feedback("REJECTED", human_feedback)
                    st.rerun()

    else:
        with st.form("generate_form"):
            st.markdown("**下达生成指令**")
            chapter_input = st.number_input("章节号", min_value=1, value=1, step=1)
            plot_prompt = st.text_area("剧情指令", placeholder="例如：在坊市捡漏买到神秘残片...")
            if st.form_submit_button("🚀 启动推演：生成本章大纲", use_container_width=True):
                if not plot_prompt:
                    st.warning("请输入指令！")
                else:
                    st.session_state.current_chapter_num = chapter_input
                    start_generation_stream(plot_prompt, chapter_input)
                    st.rerun()