import os
import json
import requests
import streamlit as st
from app.core.config import settings

# ==========================================
# ⚙️ 全局配置与状态初始化
# ==========================================
API_BASE_URL = "http://127.0.0.1:8000/novel"

st.set_page_config(page_title="StoryWeaver 总编操作台", page_icon="📖", layout="wide")

# 自定义 CSS 美化界面
st.markdown("""
<style>
    .status-badge { padding: 4px 12px; border-radius: 16px; font-weight: bold; font-size: 14px; }
    .status-idle { background-color: #e6f4ea; color: #1e8e3e; }
    .status-running { background-color: #e8f0fe; color: #1a73e8; }
    .status-review { background-color: #fef7e0; color: #f9ab00; }
    .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)


# 封装 API 请求工具函数
@st.cache_data(ttl=2)
def fetch_data(endpoint: str, key: str, default: any):
    try:
        res = requests.get(f"{API_BASE_URL}{endpoint}", timeout=5)
        return res.json().get(key, default) if res.status_code == 200 else default
    except Exception:
        return default


def fetch_book_progress(book_id):
    return fetch_data(f"/books/{book_id}/progress", "next_chapter", 1)


# 初始化 Session State
DEFAULT_STATES = {
    "thread_id": "my_new_book_01",
    "target_writing_style": None,
    "draft_content": "暂无草稿...",
    "current_beat_sheet": "",
    "predefined_world_bible": "",
    "plot_prompt_input": "",
    "show_success_effect": False,
    "app_stage": "IDLE"  # IDLE, RUNNING, REVIEW_BEAT, REVIEW_DRAFT
}

for key, default_value in DEFAULT_STATES.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

if "current_chapter_num" not in st.session_state:
    st.session_state.current_chapter_num = fetch_book_progress(st.session_state.thread_id)

# 🌟 全局运行状态判定：防止用户在流转时误触按钮打断流式连接
is_running = st.session_state.app_stage == "RUNNING"

# ==========================================
# 🧭 侧边栏：配置与资产管理
# ==========================================
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/book.png", width=60)
    st.title("资产管理中心")
    st.divider()

    # --- 书库管理 ---
    st.header("📂 项目沙盒")
    existing_books = fetch_data("/books", "books", [])
    if st.session_state.thread_id not in existing_books:
        existing_books.append(st.session_state.thread_id)

    # 🌟 运行中禁用项目切换
    selected_book = st.selectbox("📚 当前创作项目", existing_books,
                                 index=existing_books.index(st.session_state.thread_id),
                                 disabled=is_running)

    if selected_book != st.session_state.thread_id:
        st.session_state.update({
            "thread_id": selected_book,
            "current_chapter_num": fetch_book_progress(selected_book),
            "draft_content": "暂无草稿...",
            "current_beat_sheet": "",
            "app_stage": "IDLE",
            "target_writing_style": None
        })
        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        @st.dialog("➕ 创建新书项目")
        def create_new_book_dialog():
            new_book_name = st.text_input("请输入项目 ID (建议英文/数字):")
            if st.button("🚀 初始化项目", use_container_width=True, type="primary"):
                if new_book_name.strip():
                    st.session_state.update({
                        "thread_id": new_book_name.strip(),
                        "current_chapter_num": 1,
                        "draft_content": "暂无草稿...",
                        "current_beat_sheet": "",
                        "app_stage": "IDLE",
                        "target_writing_style": None
                    })
                    st.rerun()

        # 🌟 运行中禁用新建
        if st.button("➕ 新建小说", use_container_width=True, disabled=is_running): create_new_book_dialog()

    with col2:
        # 🌟 运行中禁用销毁
        if st.button("🗑️ 销毁本项目", use_container_width=True, disabled=is_running):
            try:
                requests.delete(f"{API_BASE_URL}/books/{st.session_state.thread_id}")
                st.toast("✅ 书籍已成功销毁！")
                st.session_state.app_stage = "IDLE"
                st.rerun()
            except Exception as e:
                st.error(f"销毁失败: {e}")

    st.divider()

    # --- 世界观设定 ---
    st.header("🌍 世界观与设定基座")
    st.session_state.predefined_world_bible = st.text_area(
        "录入背景设定、境界划分或金手指...",
        value=st.session_state.predefined_world_bible,
        height=120,
        help="引擎在规划大纲和生成正文时会严格遵守此处的权威设定。",
        disabled=is_running # 🌟 运行中禁用世界观修改
    )

    st.divider()

    # --- 文风克隆 ---
    st.header("🎭 文风克隆引擎")
    existing_refs = fetch_data("/references", "files", [])

    ref_tab1, ref_tab2 = st.tabs(["📁 历史提取", "⬆️ 上传解析"])
    selected_ref, uploaded_ref_content = None, None

    with ref_tab1:
        selected_ref = st.selectbox("复用历史文风", ["-- 请选择 --"] + existing_refs, disabled=is_running) if existing_refs else "-- 请选择 --"
        if not existing_refs: st.caption("暂无历史神作，请右侧上传。")

    with ref_tab2:
        uploaded_file = st.file_uploader("上传参考文本 (.txt)", type=["txt"], disabled=is_running)
        if uploaded_file:
            uploaded_ref_content = uploaded_file.read().decode("utf-8")
            try:
                with open(os.path.join(settings.REFERENCES_DIR, uploaded_file.name), "w", encoding="utf-8") as f:
                    f.write(uploaded_ref_content)
                st.toast(f"✅ 文件 `{uploaded_file.name}` 已归档")
            except Exception as e:
                st.error(f"归档失败: {e}")

    # 🌟 运行中禁用文风提取
    if st.button("🧬 提取并激活文风", use_container_width=True, type="primary", disabled=is_running):
        payload = {"reference_text": uploaded_ref_content} if uploaded_file else {"reference_filename": selected_ref}
        if payload.get("reference_text") or (selected_ref and selected_ref != "-- 请选择 --"):
            with st.spinner("🧠 深度解构文风中..."):
                res = requests.post(f"{API_BASE_URL}/analyze_style", json=payload)
                if res.status_code == 200:
                    st.session_state.target_writing_style = res.json().get("style_guide", {})
                    st.toast("🎉 文风白皮书已成功激活！")
        else:
            st.warning("请先选择或上传参考文本！")

    if st.session_state.target_writing_style:
        with st.expander("🟢 已激活文风特征", expanded=False):
            st.json(st.session_state.target_writing_style.get("novel_specific", {}).get("rules", {}))


# ==========================================
# 🚀 核心工作流与 API 交互
# ==========================================
def start_generation_stream(user_input, chapter_num):
    st.session_state.app_stage = "RUNNING"
    st.session_state.draft_content = ""

    status_box = st.empty()
    stream_box = st.empty()

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
                if not line: continue
                decoded = line.decode("utf-8")
                if not decoded.startswith("data: "): continue

                data = json.loads(decoded[6:])
                if "error" in data:
                    status_box.error(f"🚨 后端错误: {data['error']}")
                    st.session_state.app_stage = "IDLE"
                    st.stop()

                # 处理节点状态播报
                if "node" in data:
                    node_name = data["node"]
                    updates = data.get("updates", {})

                    if node_name == "Continuity_Editor":
                        editor_status = updates.get("editor_comments", "")
                        if editor_status == "FAIL":
                            status_box.error("🚨 质检拦截：发现情节抢跑或字数不足，正在强制主笔返工重修！")
                            st.session_state.draft_content = ""
                        elif editor_status == "PASS":
                            status_box.success("✅ 质检通过：逻辑核对无误！")
                        elif editor_status == "PASS_WITH_WARNING":
                            status_box.warning("⚠️ 质检警告：重试达上限，已强制放行交由总编裁决。")
                    elif node_name == "Chapter_Writer":
                        status_box.info("✍️ 金牌主笔已交稿，内审组正在核对逻辑...")
                    else:
                        status_box.info(f"🧠 智能体流转中: [{node_name}]...")

                # 处理大模型流式输出碎片
                if data.get("type") == "chunk":
                    status_box.info("🔥 主笔疯狂码字中...")
                    st.session_state.draft_content += data["content"]
                    stream_box.markdown(st.session_state.draft_content)
                    continue

                # 挂起信号处理
                if data.get("status") == "PAUSED_FOR_BEAT_SHEET_REVIEW":
                    st.session_state.app_stage = "REVIEW_BEAT"
                    break
                elif data.get("status") == "PAUSED_FOR_HUMAN_REVIEW":
                    st.session_state.app_stage = "REVIEW_DRAFT"
                    break

                # 状态同步
                updates = data.get("updates", {})
                for k in ["target_writing_style", "current_beat_sheet", "draft_content"]:
                    if k in updates: st.session_state[k] = updates[k]

    except Exception as e:
        status_box.error(f"引擎通信异常: {e}")

    # 流转结束兜底状态判定
    if st.session_state.app_stage == "RUNNING":
        if st.session_state.draft_content and st.session_state.draft_content != "暂无草稿...":
            st.session_state.app_stage = "REVIEW_DRAFT"
        elif st.session_state.current_beat_sheet:
            st.session_state.app_stage = "REVIEW_BEAT"
        else:
            st.session_state.app_stage = "IDLE"


def send_feedback(target_node, approval_status="APPROVED", beat_sheet="", feedback="", edits="", reject_chapter=False):
    if reject_chapter and target_node == "Chapter_Writer":
        requests.delete(
            f"{API_BASE_URL}/books/{st.session_state.thread_id}/chapters/{st.session_state.current_chapter_num}")
        st.session_state.update({"app_stage": "IDLE", "current_beat_sheet": ""})
        return

    payload = {
        "thread_id": st.session_state.thread_id,
        "chapter_num": st.session_state.current_chapter_num,
        "approval_status": approval_status,
        "edited_beat_sheet": beat_sheet,
        "human_feedback": feedback,
        "direct_edits": edits,
        "target_node": target_node
    }

    res = requests.post(f"{API_BASE_URL}/feedback", json=payload)
    if res.status_code == 200:
        if target_node == "Chapter_Writer" or approval_status == "REJECTED":
            st.session_state.draft_content = ""
            start_generation_stream("", st.session_state.current_chapter_num)
        else:
            st.session_state.update({
                "app_stage": "IDLE",
                "current_chapter_num": st.session_state.current_chapter_num + 1,
                "plot_prompt_input": "",
                "draft_content": "暂无草稿...",
                "current_beat_sheet": "",
                "show_success_effect": True
            })
    else:
        st.error("反馈提交失败，请检查后端状态。")


# ==========================================
# 🖥️ 主交互界面
# ==========================================
if st.session_state.show_success_effect:
    st.balloons()
    st.toast(f"🎉 第 {st.session_state.current_chapter_num - 1} 章已完美入库！", icon="🎊")
    st.session_state.show_success_effect = False

# 顶部状态栏
cols = st.columns([1, 2])
with cols[0]:
    st.title("StoryWeaver 总编台")
with cols[1]:
    stage_meta = {
        "IDLE": ("status-idle", "🟢 待机中：等待剧情指令"),
        "RUNNING": ("status-running", "⏳ 引擎轰鸣：智能体狂奔中"),
        "REVIEW_BEAT": ("status-review", "⏸️ 人类在环：请审核本章节拍器"),
        "REVIEW_DRAFT": ("status-review", "⏸️ 人类在环：请审核正文草稿")
    }
    css_class, text = stage_meta[st.session_state.app_stage]
    st.markdown(f"""
        <div style="text-align: right; padding-top: 20px;">
            <span style="font-size: 16px; margin-right: 15px;">🚀 第 <b>{st.session_state.current_chapter_num}</b> 章</span>
            <span class="status-badge {css_class}">{text}</span>
        </div>
    """, unsafe_allow_html=True)

st.divider()

# 发车控制台 (仅在待机时完整显示)
if st.session_state.app_stage == "IDLE":
    with st.container(border=True):
        st.subheader("💡 连载发车中心")
        col_inp1, col_inp2 = st.columns([1.5, 8.5])
        with col_inp1:
            chapter_input = st.number_input("目标章节", min_value=1, value=st.session_state.current_chapter_num, step=1, disabled=is_running)
        with col_inp2:
            plot_prompt = st.text_input(
                f"✍️ 第 {st.session_state.current_chapter_num} 章核心指令：",
                placeholder="例如：紧接上一章结尾，主角果断拔剑，狠狠打脸反派...",
                key="plot_prompt_input",
                disabled=is_running
            )

        # 🌟 运行中禁用发车按钮
        if st.button("🚀 启动推演引擎", use_container_width=True, type="primary", disabled=is_running):
            if not st.session_state.plot_prompt_input:
                st.warning("总编，请下达具体的剧情指令！")
            else:
                st.session_state.current_chapter_num = chapter_input
                start_generation_stream(st.session_state.plot_prompt_input, chapter_input)
                st.rerun()

# 核心内容区 (Tabs)
tab_beat, tab_draft = st.tabs(["🗺️ 章节大纲 (Beat Sheet)", "✍️ 正文工作区"])

with tab_beat:
    if st.session_state.app_stage == "REVIEW_BEAT":
        st.warning("⚠️ 引擎已挂起：请确认下方的大纲节点。您可以直接在此修改 JSON 内容改变剧情走向。")
        edited_beat = st.text_area("✍️ 大纲调整台：", value=st.session_state.current_beat_sheet, height=350)

        col_b1, col_b2 = st.columns(2)
        if col_b1.button("✅ 批准大纲，生成正文", type="primary", use_container_width=True):
            send_feedback("Chapter_Writer", beat_sheet=edited_beat)
            st.rerun()
        if col_b2.button("🔄 毙掉大纲，重新推演", use_container_width=True):
            send_feedback("Chapter_Writer", reject_chapter=True)
            st.rerun()
    else:
        if st.session_state.current_beat_sheet:
            st.code(st.session_state.current_beat_sheet, language="json")
        else:
            st.info("大纲尚未生成，请在上方下达指令。")

with tab_draft:
    if st.session_state.app_stage == "REVIEW_DRAFT":
        st.warning("⚠️ 引擎已挂起：初稿已完成。总编可直接在此处润色，或写下批注将稿件打回重做。")
        edited_draft = st.text_area("✍️ 终稿定夺（所见即所得）：", value=st.session_state.draft_content, height=450)
        human_feedback = st.text_area("📝 鞭策主笔（打回重写专用批注）：",
                                      placeholder="例如：配角太抢戏了，重新写，重点突出主角的冷酷！", height=100)

        col_d1, col_d2 = st.columns(2)
        if col_d1.button("✅ 终审完毕，直接入库", type="primary", use_container_width=True):
            send_feedback("Human_Review", approval_status="APPROVED", edits=edited_draft)
            st.rerun()
        if col_d2.button("🔄 严厉打回，强制重写", use_container_width=True):
            if not human_feedback.strip():
                st.error("打回必须给出明确的修改批注！")
            else:
                send_feedback("Human_Review", approval_status="REJECTED", feedback=human_feedback)
                st.rerun()
    else:
        if st.session_state.draft_content and st.session_state.draft_content != "暂无草稿...":
            st.markdown(st.session_state.draft_content)
        else:
            st.info("正文尚未生成。")