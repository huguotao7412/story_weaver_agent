# 📖 StoryWeaver-Agent：工业级长篇小说共创引擎 (百万字生产力版)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/Framework-LangGraph-orange)](https://python.langchain.com/docs/langgraph)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-green)](https://fastapi.tiangolo.com/)

StoryWeaver-Agent 是一款专为**百万字级长篇网文**（如番茄、塔读等下沉市场爽文生态）打造的工业级人机共创引擎。

面对当前大语言模型（LLM）在长篇创作中常见的 **“上下文遗忘导致逻辑崩塌”**、**“千篇一律的 AI 味文风”** 以及 **“黑盒生成无法控盘”** 三大痛点，本项目通过**多智能体协作 (Multi-Agent)**、**多层级动态 RAG (Hierarchical RAG)** 与 **双断点人类在环 (Dual-Breakpoint HITL)** 进行了彻底重构。系统充当不知疲倦的“代笔团队”，人类作者保留绝对的“总编决策权”，真正实现长篇连载的高效、高质量量产。

---

## ✨ 核心硬核特性 (全新升级架构)

本项目在底层存储、检索引擎与规划路径上进行了全异步工业级重构，彻底解决长篇网文生成的性能瓶颈：

* ⏸️ **双断点前置干预 (Dual-Breakpoint HITL)**
  拒绝“盲盒式”算力浪费。系统在生成《单章节拍器(大纲)》后挂起，总编确认剧情走向无误后放行；正文初稿生成后，由内部审查组与总编进行二次拦截与手动覆写，保障剧情绝对不跑偏。
* 🌲 **百万字四层树状推演 (Hierarchical Planning)**
  支持作者自带“世界观圣经”进组。系统严格执行 `全书总纲(10卷) -> 分卷大纲(三期) -> 单期统筹(10章) -> 单章节拍器(4-6 Beat)` 的四层降维打击，内置“视野遮罩”防剧透机制，彻底解决模型擅自推进时间线（抢跑）的问题。
* 🔍 **三层立体混合检索 (Hybrid RAG + Rerank)**
  告别僵硬的全量检索。系统动态切分 `Global(全局设定)`, `Volume(分卷主线)`, `Phase(近期细节)` 三层知识库。
  * **增量 BM25 极速缓存**：自研 `IncrementalBM25` 内存缓存，实现词频 O(1) 极速插入，彻底告别全量矩阵重构的 CPU 阻塞。
  * **硅基流动交叉重排**：结合 `FAISS` 召回后，经由 `BGE-Reranker` 进行终极精排，确保检索精准度。
* 💾 **纯异步 KV 状态机与动态设定补丁 (Async State Tracker)**
  弃用 TinyDB，全面升级为 `aiosqlite` 异步架构。独创“动态世界观补丁”与“悬念伏笔池”，精准管理人物生死、物品流转，以及自动追踪【挖坑/填坑】，让世界观伴随主角一同成长。
* ✍️ **分段式流式推演 (Chunked Generation)**
  主笔节点突破上下文退化瓶颈，支持根据节拍器动态计算字数权重，执行**“上半篇 + 下半篇”接力式码字**，极大提升了单章字数饱满度与细节分辨率。

---

## 🤖 智能体组织架构

系统由一位人类总编统筹，下设 8 大专业智能体节点协同工作：

1. 🎭 **Style-Analyzer (文风解构师)**：零样本解构参考神作，生成《文风白皮书》全局防 AI 味。
2. 🗺️ **Planner 架构天团 (Book/Volume/Phase/Chapter)**：分层递进拆解网文爽点公式，并在最后一层调用 RAG 智能路由动态分配检索额度。
3. ✍️ **Chapter-Writer (金牌主笔)**：苦力担当，融合文风、局部大纲与历史状态，严格遵守无缝接续锚点，进行分段式文本输出。
4. 🕵️ **Continuity-Editor (逻辑内审员)**：找茬专家，执行内部对比校验，排查 OOC（人物崩坏）、字数不足与大纲抢跑（越界红线）。
5. 🧠 **Memory-Keeper (记忆更新员)**：执行冷热数据分离，更新人物生死、物品背包，管理长线伏笔池，并执行逢十归一、逢五十归一的层级化摘要压缩。
6. 👑 **Supervisor (人类总管)**：管理双断点事务，接收总编的定夺批注、大纲重写指令或直接的本地文本覆盖。

---

## 🛠️ 技术栈与存储选型

* **编排引擎**：`LangGraph` (Async 异步状态图与条件路由)
* **存储记忆层**：
  * **图状态持久化**：`AsyncSqliteSaver` 
  * **向量检索引擎**：`FAISS` (持久化) + 增量 `BM25` (内存级缓存)
  * **状态机追踪**：`aiosqlite` (高并发安全沙盒)
* **模型基座推荐**：
  * **主笔/文风解构** (重文本生成)：`Claude 3.5 Sonnet` / `DeepSeek-V2` / 兼容 OpenAI 格式的模型
  * **逻辑审查/架构规划** (重推理分析)：`GPT-4o` 
  * **检索精排**：硅基流动 `BAAI/bge-reranker-v2-m3`
* **UI 与后端**：`FastAPI` (StreamingResponse 事件流) + `Streamlit` (多状态响应式工作台)

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
