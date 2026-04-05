# 📖 StoryWeaver-Agent：工业级长篇小说共创引擎 (百万字定制版)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/Framework-LangGraph-orange)](https://python.langchain.com/docs/langgraph)

StoryWeaver-Agent 是一款专为**百万字级长篇网文**（如番茄、塔读等下沉市场爽文生态）打造的工业级人机共创引擎。

面对当前大语言模型（LLM）在长篇创作中常见的 **“上下文遗忘导致逻辑崩塌”**、**“千篇一律的 AI 味文风”** 以及 **“黑盒生成无法控盘”** 三大痛点，本项目通过**多智能体协作 (Multi-Agent)** 与 **两段式事务记忆 (Two-Phase Commit)** 进行了彻底重构。系统充当不知疲倦的“代笔团队”，人类作者保留绝对的“总编决策权”，真正实现长篇连载的高效、高质量量产。

---

## ✨ 核心硬核特性 (v3.0 百万字重构版)

为了跨越单体大模型的上下文极限，本项目在架构上彻底重构了底层存储与规划路径：

* 🌲 **四层树状推演规划 (Hierarchical Planning)**
  彻底告别“写到哪算哪”。系统严格执行 `全书总纲(10卷) -> 分卷大纲(前中后3期) -> 单期统筹(10章) -> 单章节拍器(3-5个爽点)` 的四层降维打击，确保百万字主线不崩盘。
* 🧊 **冷热地图隔离与冻结 (Map-based Data Freezing)**
  底层 KV 数据库支持 `active_map` 机制。当主角跨越大地图（如从新手村飞升仙界），系统自动冻结旧地图的配角与无关物品，彻底释放 Prompt 上下文，拒绝中后期角色幻觉。
* 📚 **三层立体 RAG 检索引擎 (Hierarchical RAG)**
  摒弃传统的大杂烩向量库。系统维护 `Global (死设定与大事件)`、`Volume (本卷主线)`、`Phase (本期微观动作)` 三层检索架构。单期结束自动“阅后即焚”底层细节，防止检索稀释与记忆污染。
* 🕳️ **伏笔生命周期管理 (Foreshadowing Tracker)**
  独创“悬念伏笔池”。每章自动提取新结的死仇与挖的坑（入池），规划师在后续规划中会看着池子主动安排剧情，主角报仇后系统自动抹除记录（填坑），实现严密的因果闭环。
* 🎭 **零样本动态文风克隆 (Dynamic Style Alignment)**
  支持上传神作片段，系统零样本多维度解构（句式、词汇、情绪、动静比），提炼《文风白皮书》并全局注入主笔 Prompt，彻底消除 AI 味。
* ⏸️ **人类最高指令覆盖 (Human Override HITL)**
  在草稿入库前强制挂起工作流。人类总编如不满意，可打回并附加最高权限的批注指令（如：“反派不够嚣张，重写”），强行干预 AI 的下一步生成。

---

## 🤖 智能体组织架构

系统由一位人类总编统筹，下设 7 大专业智能体节点协同工作：

1. 🎭 **Style-Analyzer (文风解构师)**：【前置节点】解构参考文本，生成《文风白皮书》。
2. 🗺️ **Planner 架构天团**：由 `Book-Planner`、`Volume-Planner`、`Phase-Planner`、`Chapter-Planner` 组成，层层递进拆解网文爽点公式。
3. ✍️ **Chapter-Writer (金牌主笔)**：苦力担当，融合文风、单章大纲与历史状态，输出明快、极具网文感的正文草稿。
4. 🕵️ **Continuity-Editor (逻辑审查员)**：找茬专家，执行内部对比校验，排查 OOC、战力崩坏与逻辑 Bug。
5. 🧠 **Memory-Keeper (记忆更新员)**：【数据入库枢纽】执行冷热数据分离，动态更新人物生死至 KV 数据库，将事件分类灌入三层 RAG，并管理伏笔池。
6. 👑 **Supervisor (人类总管)**：管理两段式事务记忆，在总编未点击“批准”前，草稿只留在隔离区，绝不污染核心数据库。

---

## 🛠️ 技术栈与存储选型

* **编排引擎**：`LangGraph` (基于 StateGraph 与 Breakpoints 实现双向循环流转与人类拦截)
* **存储记忆层**：
  * **向量检索引擎**：`FAISS` (三分层独立索引架构)
  * **KV 状态追踪**：`TinyDB` (轻量级本地 JSON 数据库，记录冷热地图、角色物品树与伏笔池)
* **模型基座推荐**：
  * **主笔/文风解构** (重文本生成)：`Claude 3.5 Sonnet` / `DeepSeek-V2`
  * **逻辑审查/规划** (重推理分析)：`GPT-4o` / `DeepSeek-Chat`
* **UI 与后端**：`FastAPI` (流式响应) + `Streamlit` (双栏人机协同交互台)

---

## 🚀 快速开始

### 1. 环境准备

建议使用 Python 3.10+ 环境：

```bash
# 克隆仓库
git clone [https://github.com/yourusername/StoryWeaver-Agent.git](https://github.com/yourusername/StoryWeaver-Agent.git)
cd StoryWeaver-Agent

# 创建并激活虚拟环境
python -m venv venv
source venv/bin/activate  # Windows 用户使用: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
 ```
### 2.配置 API Key
在项目根目录创建 .env 文件，并根据你的实际情况填入大模型 API 密钥：
```bash
MAIN_LLM_API_KEY=your_deepseek_or_gpt4o_key
FAST_LLM_API_KEY=your_glm_or_faster_model_key
EMBEDDING_API_KEY=your_embedding_model_key
 ```
### 3.启动服务
本项目采用前后端分离的架构，请打开两个终端分别运行：
1. 后端服务：
```bash
python main.py
 ```
2. 前端服务：
```bash
streamlit run ui.py
 ```
