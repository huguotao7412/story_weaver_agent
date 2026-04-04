# ui.py
import os
import streamlit as st
import requests
import json
import uuid

# 🌟 引入全局配置，确保路径和后端完全一致
from app.core.config import settings

# === 配置后端 API 地址 ===
API_BASE_URL = "http://127.0.0.1:8000/novel"

# === 页面基础设置 ===
st.set_page_config(
    page_title="StoryWeaver-Agent 总编操作台",
    page_icon="📖",
    layout="wide"
)

# === 初始化 Session State ===
if "target_writing_style" not in st.session_state:
    st.session_state.target_writing_style = None
if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"thread_{uuid.uuid4().hex[:8]}"
if "draft_content" not in st.session_state:
    st.session_state.draft_content = "暂无草稿..."
if "current_beat_sheet" not in st.session_state:
    st.session_state.current_beat_sheet = ""
if "is_paused_for_review" not in st.session_state:
    st.session_state.is_paused_for_review = False
if "system_status" not in st.session_state:
    st.session_state.system_status = "🟢 待机中"
if "editor_comments" not in st.session_state:
    st.session_state.editor_comments = ""

# === 🌟 侧边栏：文风提取、上传与库管理 ===
with st.sidebar:
    st.header("🎭 全局文风克隆引擎")

    # --- 模块 1：上传新文件 ---
    st.markdown("上传 `.txt` 神作片段 (1000-3000字)，让 AI 自动解构文风！")
    uploaded_file = st.file_uploader("选择新的参考文本", type=["txt"])

    if uploaded_file is not None:
        ref_content = uploaded_file.read().decode("utf-8")

        # 物理归档落盘
        try:
            save_path = os.path.join(settings.REFERENCES_DIR, uploaded_file.name)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(ref_content)
            st.success(f"📁 文件已保存并加入参考库: `{uploaded_file.name}`")
        except Exception as e:
            st.error(f"物理归档失败: {e}")

        if st.button("🧬 立即提取该文风", use_container_width=True, type="primary"):
            with st.spinner("文风解构师正在逐句分析..."):
                try:
                    res = requests.post(f"{API_BASE_URL}/analyze_style", json={"reference_text": ref_content})
                    if res.status_code == 200:
                        st.session_state.target_writing_style = res.json().get("style_guide", {})
                        st.success("✅ 文风白皮书已生成并激活！")
                    else:
                        st.error("提取失败，请重试。")
                except Exception as e:
                    st.error(f"网络异常: {e}")

    st.divider()

    # --- 模块 2：本地参考神作库管理 ---
    st.subheader("📚 本地参考神作库")

    if os.path.exists(settings.REFERENCES_DIR):
        existing_files = [f for f in os.listdir(settings.REFERENCES_DIR) if f.endswith(".txt")]

        if not existing_files:
            st.info("暂无已保存的参考文本。")
        else:
            # 遍历渲染文件列表
            for f_name in existing_files:
                col_name, col_del, col_ext = st.columns([5, 2, 3])

                with col_name:
                    st.markdown(f"📄 `{f_name}`")

                with col_del:
                    # 删除按钮
                    if st.button("🗑️", key=f"del_{f_name}", help="删除此文件"):
                        try:
                            os.remove(os.path.join(settings.REFERENCES_DIR, f_name))
                            st.rerun()  # 🌟 重点：删除后立刻刷新页面，更新列表
                        except Exception as e:
                            st.error(f"删除失败: {e}")

                with col_ext:
                    # 快捷提取按钮
                    if st.button("🧬提取", key=f"ext_{f_name}", help="直接提取此文件的文风"):
                        with st.spinner(f"正在分析 {f_name}..."):
                            try:
                                # 读取本地文件内容
                                with open(os.path.join(settings.REFERENCES_DIR, f_name), "r", encoding="utf-8") as f:
                                    local_content = f.read()

                                # 请求后端提取文风
                                res = requests.post(f"{API_BASE_URL}/analyze_style",
                                                    json={"reference_text": local_content})
                                if res.status_code == 200:
                                    st.session_state.target_writing_style = res.json().get("style_guide", {})
                                    st.success(f"✅ 已激活 `{f_name}` 的文风！")
                                else:
                                    st.error("提取失败。")
                            except Exception as e:
                                st.error(f"读取或提取异常: {e}")

    st.divider()

    # --- 模块 3：当前激活的文风展示 ---
    if st.session_state.target_writing_style:
        with st.expander("🟢 当前正在使用的文风特征", expanded=True):
            style_info = st.session_state.target_writing_style
            rules = style_info.get("novel_specific", {}).get("rules", style_info)
            st.json(rules)


# === API 调用函数 ===
def start_generation_stream(user_input, chapter_num):
    """调用 /stream 接口并解析 SSE 流数据"""
    st.session_state.system_status = "⏳ 引擎运转中，正在生成大纲与草稿..."
    st.session_state.is_paused_for_review = False

    payload = {
        "user_input": user_input,
        "thread_id": st.session_state.thread_id,
        "chapter_num": chapter_num,
        "target_writing_style": st.session_state.target_writing_style
    }

    try:
        with requests.post(f"{API_BASE_URL}/stream", json=payload, stream=True) as response:
            if response.status_code != 200:
                st.error(f"后端报错: {response.text}")
                return

            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode("utf-8")
                    if decoded_line.startswith("data: "):
                        data_str = decoded_line[6:]
                        try:
                            data = json.loads(data_str)

                            if data.get("status") == "PAUSED_FOR_HUMAN_REVIEW":
                                st.session_state.is_paused_for_review = True
                                st.session_state.system_status = "⏸️ 内部审查完毕，等待人类总编批示！"
                                break

                            node_name = data.get("node", "")
                            updates = data.get("updates", {})

                            if "current_beat_sheet" in updates:
                                st.session_state.current_beat_sheet = updates["current_beat_sheet"]
                            if "draft_content" in updates:
                                st.session_state.draft_content = updates["draft_content"]
                            if "editor_comments" in updates:
                                st.session_state.editor_comments = updates["editor_comments"]

                        except json.JSONDecodeError:
                            pass
    except Exception as e:
        st.error(f"网络请求异常: {e}")


def send_human_feedback(approval_status, feedback_text):
    """调用 /feedback 接口发送人类审批结果"""
    payload = {
        "thread_id": st.session_state.thread_id,
        "approval_status": approval_status,
        "human_feedback": feedback_text
    }
    try:
        response = requests.post(f"{API_BASE_URL}/feedback", json=payload)
        if response.status_code == 200:
            st.success(f"指令已发送！状态: {approval_status}")
            st.session_state.is_paused_for_review = False

            if approval_status == "REJECTED":
                current_chap = st.session_state.get("current_chapter_num", 1)
                start_generation_stream("人类已打回，请重新生成", current_chap)
            else:
                st.session_state.system_status = "✅ 章节已批准并入库！"
        else:
            st.error(f"发送反馈失败: {response.text}")
    except Exception as e:
        st.error(f"网络请求异常: {e}")


# === UI 布局构建 ===
st.title("📖 StoryWeaver-Agent 总编操作台")
st.markdown(f"**当前事务 Thread ID**: `{st.session_state.thread_id}` | **系统状态**: {st.session_state.system_status}")
st.divider()

col_left, col_right = st.columns([6, 4])

with col_left:
    st.subheader("📝 事务草稿区")

    tab1, tab2, tab3 = st.tabs(["✍️ 当前正文草稿", "🗺️ 本章节拍器", "🕵️ 内部审查意见"])

    with tab1:
        st.markdown(
            f"""
            <div style="height: 600px; overflow-y: scroll; padding: 15px; border: 1px solid #ddd; border-radius: 5px; background-color: #f9f9f9; color: #333;">
                {st.session_state.draft_content.replace(chr(10), '<br>')}
            </div>
            """,
            unsafe_allow_html=True
        )

    with tab2:
        st.text_area("单章大纲 (JSON)", value=st.session_state.current_beat_sheet, height=500, disabled=True)

    with tab3:
        if st.session_state.editor_comments == "PASS":
            st.success("✅ 逻辑审查员判定：PASS (逻辑一致，无漏洞)")
        elif st.session_state.editor_comments:
            st.error(f"❌ 逻辑审查员判定异常：\n\n{st.session_state.editor_comments}")
        else:
            st.info("等待内部审查...")

with col_right:
    st.subheader("👑 创作指令与批注台")

    with st.form("generate_form"):
        st.markdown("**第一步：下达本章生成指令**")
        chapter_input = st.number_input("当前章节号", min_value=1, value=1, step=1)
        plot_prompt = st.text_area("剧情指令/脑洞",
                                   placeholder="例如：写一段主角在坊市捡漏买到神秘残片的剧情，反派来嘲讽结果被打脸...")

        submitted = st.form_submit_button("🚀 生成本章草稿", use_container_width=True)
        if submitted:
            if not plot_prompt:
                st.warning("请输入剧情指令！")
            else:
                st.session_state.current_chapter_num = chapter_input
                start_generation_stream(plot_prompt, chapter_input)
                st.rerun()

    st.divider()

    st.markdown("**第二步：人类总编最高决策**")

    if st.session_state.is_paused_for_review:
        st.warning("⚠️ 内部 AI 互搏已完成，草稿正等待您的决断。")

        human_feedback = st.text_area("修改批注 (如果打回，主笔将根据此批注重写)：",
                                      placeholder="例如：主角的态度太软弱了，要体现出杀伐果断，重新写结尾。")

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("✅ 批准入库 (APPROVED)", type="primary", use_container_width=True):
                send_human_feedback("APPROVED", "")
                st.rerun()
        with col_btn2:
            if st.button("🔄 打回重写 (REJECTED)", use_container_width=True):
                if not human_feedback:
                    st.error("打回重写必须填写修改批注！")
                else:
                    send_human_feedback("REJECTED", human_feedback)
                    st.rerun()
    else:
        st.info("系统正在运行或待机中，当前无需要审批的草稿。")