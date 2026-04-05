# 📖 StoryWeaver-Agent：工业级长篇小说共创引擎 (百万字生产力版)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/Framework-LangGraph-orange)](https://python.langchain.com/docs/langgraph)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-green)](https://fastapi.tiangolo.com/)

StoryWeaver-Agent 是一款专为**百万字级长篇网文**（如番茄、塔读等下沉市场爽文生态）打造的工业级人机共创引擎。

面对当前大语言模型（LLM）在长篇创作中常见的 **“上下文遗忘导致逻辑崩塌”**、**“千篇一律的 AI 味文风”** 以及 **“黑盒生成无法控盘”** 三大痛点，本项目通过**多智能体协作 (Multi-Agent)**、**多层级动态 RAG (Hierarchical RAG)** 与 **双断点人类在环 (Dual-Breakpoint HITL)** 进行了彻底重构。系统充当不知疲倦的“代笔团队”，人类作者保留绝对的“总编决策权”，真正实现长篇连载的高效、高质量量产。

---

## ✨ 核心硬核特性 (v3.5 全新升级)

本项目在架构上彻底重构了底层存储与规划路径，解决了多项开源小说引擎的致命弱点：

* ⏸️ **双断点前置干预 (Dual-Breakpoint HITL)**
  拒绝“盲盒式”算力浪费。系统在生成《单章节拍器(大纲)》后进行首次拦截，总编确认剧情走向无误后，再投入算力生成 3000 字正文；正文生成后进行二次拦截润色。每一步都在人类绝对掌控之下。
* 📂 **多项目沙盒隔离 (Multi-Tenant Isolation)**
  支持输入 `Book ID` 建书。底层的 `FAISS` 向量库与 `TinyDB` 状态机根据书名进行物理目录级隔离。随时切换书名即可实现完美“断点续写”，绝无跨书记忆污染。
* 🌲 **四层树状推演与世界观注入 (Hierarchical Planning)**
  支持作者自带“世界观圣经”进组。系统严格执行 `全书总纲(10卷) -> 分卷大纲(三期) -> 单期统筹(10章) -> 单章节拍器(动态RAG)` 的四层降维打击，百万字主线凝结不散。
* 🧭 **轻量级动态 RAG 路由 (Query Rewriter)**
  告别僵硬的相似度检索。生成单章前，内置路由 Agent 极速分析当前剧情重点，动态分配 `Global`, `Volume`, `Phase` 三层向量库的检索 K 值额度（例如：战斗场景加大近期动作回忆，探险场景加大远古设定检索）。
* 🧊 **冷热地图隔离与伏笔池 (Map Freezing & Thread Tracker)**
  底层数据库支持 `active_map` 机制，跨大地图自动冻结旧配角。独创“悬念伏笔池”，挖坑登记，填坑抹除，实现严密的网文长线因果闭环。
* ⚡ **全异步流式前端 (Async Streaming UI)**
  后端采用 FastAPI `astream` 结合 LangGraph 异步事件循环，前端采用 Markdown 丝滑打字机渲染，彻底告别阻塞卡顿与输入框失去焦点的闪烁问题。

---

## 🤖 智能体组织架构

系统由一位人类总编统筹，下设 7 大专业智能体节点协同工作：

1. 🎭 **Style-Analyzer (文风解构师)**：零样本解构参考神作，生成《文风白皮书》全局防 AI 味。
2. 🗺️ **Planner 架构天团**：层层递进拆解爽点公式，并在最后一层调用 Query Rewriter 进行智能检索。
3. ✍️ **Chapter-Writer (金牌主笔)**：苦力担当，融合文风、单章大纲与历史状态，输出正文草稿。
4. 🕵️ **Continuity-Editor (逻辑审查员)**：找茬专家，执行内部对比校验，排查 OOC、战力崩坏与逻辑 Bug。
5. 🧠 **Memory-Keeper (记忆更新员)**：执行冷热数据分离，更新人物生死并管理长线伏笔池。
6. 👑 **Supervisor (人类总管)**：管理双断点事务，接收总编的批注与大纲重写指令。

---

## 🛠️ 技术栈与存储选型

* **编排引擎**：`LangGraph` (Async 异步状态图与双断点挂起机制)
* **存储记忆层**：
  * **检查点记忆**：`AsyncSqliteSaver` (图状态持久化)
  * **向量检索引擎**：`FAISS` (三分层动态路由架构)
  * **KV 状态追踪**：`TinyDB` (物理隔离的 JSON 沙盒)
* **模型基座推荐**：
  * **主笔/文风解构** (重文本生成)：`Claude 3.5 Sonnet` / `DeepSeek-V2`
  * **逻辑审查/架构规划** (重推理分析)：`GPT-4o` / `DeepSeek-Chat`
  * **检索路由** (极速短思考)：`GLM-4-Flash` 等 Fast 模型
* **UI 与后端**：`FastAPI` (StreamingResponse) + `Streamlit` (双栏响应式操作台)

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
### 4.使用说明
1.在网页侧边栏 项目/书目管理 中输入你的专属 Book ID（例如：xiuxian_book_01）。

2.可选：在 世界观基座 中填入你预先构思好的背景设定、境界划分和金手指。

3.在右侧主控制台输入初始剧情脑洞，点击 “生成本章大纲”，开始体验工业级双断点生成流！
