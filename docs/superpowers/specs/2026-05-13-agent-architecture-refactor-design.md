# StoryWeaver Agent 架构重构设计

**日期**：2026-05-13  
**状态**：已确认  
**范围**：Agent 架构重构 + 提示词外提 + State 分组

---

## 1. 动机与目标

当前项目（~3300 行）存在三个核心问题：

1. **Agent 扩展性差**：节点在 `graph.py` 中硬编码注册，路由逻辑散落在 `planner_router` / `editor_router` / `human_review_router` 函数中，新增节点需改动 graph.py、state.py、可能还要改 routes.py。
2. **提示词管理混乱**：所有 System Prompt 以多行字符串硬编码在 Python 文件中，修改提示词看不出 diff，版本回退困难，且与代码逻辑耦合。
3. **State 平铺臃肿**：`TomatoNovelState` 20+ 字段在单一 TypedDict 中平铺，语义边界模糊。

**目标**：在保持零外部服务依赖的前提下，用最小改动将架构升级为可配置编排的 Agent 插件体系。

---

## 2. 设计决策

### 2.1 Agent 基类接口

定义 `app/agents/base.py`，提供所有 Agent 节点共用的抽象：

```
BaseAgent (ABC)
├── name: str              # 子类定义，如 "Book_Planner"
├── prompt_file: str        # 子类定义，如 "prompts/book_planner.yaml"
├── execute(state) → dict  # 子类必须实现的核心入口
├── load_prompt(**kwargs)  # 基类：加载 YAML prompt + Jinja2 变量插值
├── safe_json_invoke(...)  # 基类：安全 LLM JSON 调用（重试+解析）
└── extract_json(text)     # 基类静态方法：JSON 提取
```

**约束**：
- `execute()` 是唯一入口，接收完整 state dict，返回部分 state dict（LangGraph 的 `add_messages` reducer 自动合并）
- `load_prompt()` 内部读取 `prompts/<agent_name>.yaml`，用 Jinja2 做 `{{ variable }}` 插值
- `safe_json_invoke()` 从 all_planner.py 原有 `_safe_json_invoke` 迁移，所有需要结构化 JSON 输出的 Agent 共用
- `extract_json()` 从现有的 `extract_json()` 迁移为静态方法

### 2.2 Workflow YAML 拓扑定义

创建 `workflow.yaml`，将 `graph.py` 中的节点注册、边连接、条件路由全部声明化：

```yaml
version: "1.0"
nodes: [...]           # name + agent 映射
edges: [...]           # 固定边
conditional_routes:    # 条件路由（简单表达式从 state 取值）
  planner_router:
    conditions:
      - check: "not book_outline"    → Book_Planner
      - check: "is_new_volume"       → Volume_Planner
      - check: "is_new_phase"        → Phase_Planner
      - default: Chapter_Planner
  editor_router: ...
  human_review_router: ...
interrupt_before: [...] # LangGraph interrupt 配置
```

**路由表达式规范**：`check` 字段使用简单布尔表达式，允许的变量来自 state 顶层键。复杂逻辑仍可写 Python 函数覆盖（在 `app/agents/routers.py` 中集中管理）。

**graph.py 改造**：从硬编码节点注册变成一个通用编排器 `build_workflow()`，读取 YAML → 注册节点 → 建立边 → 设置条件路由 → compile 返回。条件路由优先匹配 YAML 表达式，YAML 中未覆盖的引用 `routers.py` 中的 Python 函数。

### 2.3 提示词外提

- 每个 Agent 的 System Prompt 独立 YAML 文件，存放在 `prompts/` 目录
- 文件名对应 Agent 的 `prompt_file` 属性（如 `book_planner.yaml`）
- YAML 结构：`system_prompt: |` + `human_prompt_template: |`，用 Jinja2 `{{ var }}` 做变量插值
- Agent 调用 `self.load_prompt(chapter_num=5, world_bible="...")` 获取组装好的 LangChain Message 列表

### 2.4 State 分组

将当前 `TomatoNovelState` 的 20 个平铺字段分为 4 个子 TypedDict：

```python
class GlobalConfig(TypedDict):      # 全局只读配置
    book_id, world_bible_context, target_writing_style

class PlanningContext(TypedDict):   # 四层大纲规划
    book_outline_context, current_volume_phases, current_phase_chapters,
    current_beat_sheet, is_book_initialized, is_volume_initialized, is_phase_initialized

class ChapterWorkspace(TypedDict):  # 当前章节工作区
    current_chapter_num, draft_path, recent_chapters_summary,
    rag_history_context, previous_chapter_ending, editor_comments,
    internal_revision_count, revision_history

class HITLContext(TypedDict):       # 人类干预区
    human_approval_status, human_feedback, direct_edits, user_input

class TomatoNovelState(GlobalConfig, PlanningContext, ChapterWorkspace, HITLContext, total=False):
    pass
```

**影响范围**：`TomatoNovelState` 拆分后，各 Agent 的 `execute()` 函数内部通过 state 键访问字段（行为不变），只是类型定义更清晰。下游 consumer（graph.py, routes.py）无需任何改动。

---

## 3. 文件结构变更

```
变更前                              变更后
──────                              ──────
app/agents/                         app/agents/
├── graph.py                        ├── base.py              (新增：抽象基类)
├── supervisor.py                   ├── graph.py             (重写：通用编排器)
└── workers/                        ├── routers.py           (新增：路由函数集中)
    ├── all_planner.py              ├── registry.py          (新增：Agent注册表)
    ├── chapter_writer.py           ├── supervisor.py        (改：继承BaseAgent)
    ├── continuity_editor.py        ├── book_planner.py      (改：从all_planner拆分)
    ├── memory_keeper.py            ├── volume_planner.py    (改：从all_planner拆分)
    └── style_analyzer.py           ├── phase_planner.py     (改：从all_planner拆分)
                                    ├── chapter_planner.py   (改：从all_planner拆分)
app/core/                           ├── chapter_writer.py    (改：继承BaseAgent)
├── state.py      (改：四组拆分)    ├── continuity_editor.py  (改：继承BaseAgent)
└── ...                             ├── memory_keeper.py     (改：继承BaseAgent)
                                    └── style_analyzer.py    (改：继承BaseAgent)

                                    prompts/                 (新增：提示词目录)
                                    ├── book_planner.yaml
                                    ├── volume_planner.yaml
                                    ├── phase_planner.yaml
                                    ├── chapter_planner.yaml
                                    ├── chapter_writer.yaml
                                    ├── continuity_editor.yaml
                                    ├── memory_keeper.yaml
                                    └── style_analyzer.yaml

                                    workflow.yaml            (新增：拓扑定义)

app/api/                            app/api/
├── routes.py     (不改)            └── routes.py            (不改)
└── server.py     (不改)            └── server.py            (不改)
```

**不动的文件**：`main.py`、`app/api/routes.py`、`app/api/server.py`、`app/core/config.py`、`app/core/llm_factory.py`、`app/memory/kv_tracker.py`、`app/memory/rag_engine.py`、`protocols/a2a_schemas.py`、`protocols/hitl_schemas.py`、`ui.py`

---

## 4. 数据流不变性保证

以下行为必须保持不变：

1. **SSE 流式输出**：`routes.py` 的 `stream_mode=["updates", "messages"]` 不变，前端 `ui.py` 不做任何改动
2. **LangGraph checkpointer**：`server.py` 的 `AsyncSqliteSaver` 挂载方式不变，`config` 传参不变
3. **HITL 中断/恢复**：`interrupt_before=["Chapter_Writer", "Human_Review"]` 不变，`aupdate_state` 唤醒方式不变
4. **跨章节状态继承**：`routes.py` 中从 `prev_config` 捞取历史 state 的逻辑不变
5. **所有 API 接口**：`/stream`、`/feedback`、`/books`、`/analyze_style` 等路由签名和返回格式不变

---

## 5. 风险与回滚策略

| 风险 | 缓解措施 |
|------|---------|
| `all_planner.py` 拆分为 4 个文件后 import 断裂 | `registry.py` 集中维护映射，各 Agent 独立 import llm/tracker/rag |
| YAML 路由表达式覆盖不了复杂条件 | `routers.py` 保留 Python 函数版本作为兜底，YAML 优先匹配 |
| State 多继承导致 TypedDict 行为异常 | 使用 `total=False` 确保所有字段可选，与现有 LangGraph `add_messages` reducer 兼容 |
| 提示词迁移后 Jinja2 转义问题 | 转义测试覆盖所有 `{{ }}` 和 `{% %}` 模板变量，启动时做一次 dry-run 校验 |

**回滚**：所有改动在独立分支上进行，通过 `git diff` 可逐文件对比变更。如有问题，回退到主分支即可。

---

## 6. 测试策略

1. **启动冒烟测试**：`python -c "from app.agents.registry import agent_registry; print(agent_registry)"` — 验证所有 Agent 注册成功
2. **Prompt 加载测试**：每个 Agent 调用 `load_prompt()` 验证 YAML 解析 + Jinja2 插值不出错
3. **Workflow 编译测试**：`python -c "from app.agents.graph import build_workflow; wf = build_workflow(); print(wf.get_graph())"` — 验证 YAML → StateGraph 编译成功
4. **端到端测试**：用固定 seed 章节输入调用 `/stream` 接口，对比重构前后返回的 `draft_content` 长度和关键字段（`editor_comments`、`current_beat_sheet` 是否存在），确保行为不变

---

## 7. 前置新增依赖

- **PyYAML**：已有（LangChain 依赖）
- **Jinja2**：已有（FastAPI 依赖）
- **loguru**：新增，替代 print 做结构化日志

无需新增任何外部服务。
