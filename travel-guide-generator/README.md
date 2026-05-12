# 智能旅游攻略生成器 (Travel Guide Generator)

一个基于 Flask + 多 Agent 动态编排的智能旅游攻略生成系统。通过对话式交互，模拟专业旅行顾问的工作流——从需求收集、多专家协作规划，到质量检查与一键导出（HTML + PDF），生成可直接落地执行的高品质旅游攻略。

---

## 核心特性

### 多 Agent 动态编排架构
- **编排器（Orchestrator）**：`行程规划师` 负责与用户对话、收集需求、调度专家 Agent
- **领域专家（Experts）**：`景点规划`、`酒店规划`、`美食搜索`、`路线规划` 四大专家分工协作
- **检查师（Checker）**：`攻略检查师` 自动审查攻略的完整性、逻辑一致性和预算准确性
- **并行/串行执行**：专家按依赖分组（Group），组内并行、组间串行，提升生成效率

### 对话式四阶段工作流
1. **需求收集（REQUIREMENT）**：Planner 通过对话收集目的地、时间、人数、预算等 13 维需求
2. **需求确认（REQUIREMENT_CONFIRMED）**：结构化展示提取的需求，用户确认或修改
3. **攻略生成（EXECUTION）**：Planner 调度四大专家分模块生成攻略内容
4. **质量检查（COMPLETE）**：Checker 自动审查并输出问题列表

### Prompt 模板分层系统
- 支持 **core / role / format** 三层模板架构
- 模板存储于数据库，支持运行时热更新
- 支持变量注入与缺失变量检测
- 首次启动自动迁移旧版 `.txt` 提示词文件

### Skill 扩展与工具调用
- 内置 `web_search` Skill：通过 DuckDuckGo 实时搜索机票、酒店、门票等最新信息
- 基于 OpenAI Function Calling 协议，LLM 可自主决定是否调用外部工具
- 支持动态发现：将新 Skill 文件放入 `skills/` 目录即可自动注册

### 多模型统一接入
- 统一抽象层支持 **OpenAI**、**Anthropic Claude**、**DeepSeek**、**通义千问** 等任意兼容模型
- 支持流式输出（SSE），实时显示推理过程和生成内容
- 每个 Agent 可独立配置模型参数（模型、温度、max_tokens、reasoning_effort 等）

### 一键导出
- **HTML**：移动端友好的响应式页面，支持表格、列表、引用块等丰富排版
- **PDF**：通过 Chrome Headless 生成，适合打印分享

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 LLM

编辑 `config.yaml`，为 Planner 和 Checker 配置 API Key：

```yaml
llm:
  planner:
    provider: openai-compatible
    model: deepseek-v4-pro
    api_key: sk-your-key
    api_base: https://api.deepseek.com
    temperature: 0.7
    max_tokens: 4096
    thinking_enabled: true
    reasoning_effort: max

  checker:
    provider: openai-compatible
    model: deepseek-v4-pro
    api_key: sk-your-key
    api_base: https://api.deepseek.com
    temperature: 0.3
    thinking_enabled: true
    reasoning_effort: high
```

也支持通过环境变量配置（前缀 `PLANNER_` / `CHECKER_`）。

### 3. 启动应用

```bash
python app.py
```

打开浏览器访问 `http://localhost:5002`

---

## 使用流程

1. **输入需求**：在聊天界面告诉 Planner 你的目的地、出行时间、人数、预算等
2. **确认需求**：Planner 提取并结构化展示需求，你确认或要求修改
3. **生成攻略**：Planner 依次调度：
   - 景点专家（Group 1）梳理景点菜单与片区
   - 酒店专家（Group 2）推荐住宿方案
   - 美食专家（Group 3）挖掘本地餐厅
   - 路线专家（Group 4）规划最优行程与交通
4. **质量检查**：Checker 自动审查攻略完整性、逻辑一致性和预算准确性
5. **导出攻略**：一键导出 HTML（手机查看）或 PDF（打印分享）

---

## 项目结构

```
travel-guide-generator/
├── app.py                          # Flask 应用入口
├── config.py                       # 配置管理（LLMConfig / AppConfig）
├── models.py                       # SQLAlchemy 数据模型
├── routes.py                       # API 路由与视图逻辑
├── requirements.txt
├── config.yaml                     # LLM 与 Skill 配置文件
│
├── services/
│   ├── llm_service.py              # LLM 统一调用层（OpenAI / Anthropic / Compatible）
│   ├── chat_service.py             # 对话状态机（4 阶段流程管理）
│   ├── orchestration_engine.py     # 多 Agent 编排引擎（并行/串行调度）
│   ├── agent_registry_service.py   # Agent 注册表（缓存 + 关系管理）
│   ├── prompt_template_service.py  # Prompt 模板分层管理（core/role/format）
│   └── init_service.py             # 默认 Agent / 关系 / 模板初始化
│
├── agents/
│   ├── planner_agent.py            # 行程规划师（Orchestrator）
│   ├── checker_agent.py            # 攻略检查师（Checker）
│   └── prompts/                    # 系统提示词文件（首次启动自动迁移到数据库）
│       ├── planner_system.txt
│       ├── checker_system.txt
│       ├── scene_expert.txt
│       ├── hotel_expert.txt
│       ├── food_expert.txt
│       └── route_expert.txt
│
├── skills/
│   ├── base.py                     # Skill 抽象基类
│   ├── registry.py                 # Skill 动态发现与注册
│   └── web_search_skill.py         # DuckDuckGo 联网搜索 Skill
│
├── utils/
│   ├── md2html.py                  # Markdown → 移动端友好 HTML
│   └── pdf_export.py               # HTML → PDF（Chrome Headless）
│
├── templates/                      # Jinja2 页面模板
│   ├── index.html                  # 主聊天界面
│   ├── agents.html                 # Agent 管理页
│   ├── orchestration.html          # 编排关系管理页
│   ├── config.html                 # LLM 配置页
│   └── base.html
│
├── static/                         # CSS / JS 前端资源
│   ├── css/
│   └── js/
│
└── instance/
    └── app.db                      # SQLite 数据库（运行时创建）
```

---

## 多模型配置示例

### DeepSeek V4

```yaml
llm:
  planner:
    provider: openai-compatible
    model: deepseek-v4-pro
    api_key: sk-xxx
    api_base: https://api.deepseek.com
    thinking_enabled: true
    reasoning_effort: max
```

### OpenAI GPT-4o

```yaml
llm:
  planner:
    provider: openai
    model: gpt-4o
    api_key: sk-xxx
```

### Anthropic Claude 3

```yaml
llm:
  planner:
    provider: anthropic
    model: claude-3-sonnet-20240229
    api_key: sk-ant-xxx
```

---

## Agent 管理

系统内置 6 个默认 Agent，均可在 **Agent 管理页** (`/agents`) 动态增删改：

| Agent | 角色类型 | 职责 |
|-------|---------|------|
| planner | orchestrator | 与用户对话、收集需求、编排专家 |
| checker | checker | 审查攻略质量 |
| scene_expert | expert | 梳理景点、按片区分类、推荐游览顺序 |
| hotel_expert | expert | 推荐高性价比住宿方案 |
| food_expert | expert | 挖掘本地特色美食与餐厅 |
| route_expert | expert | 规划最优行程路线与交通方案 |

### 编排关系

在 **编排管理页** (`/orchestration`) 可配置 Agent 间的触发关系：
- `source_agent` → `target_agent`
- `trigger_stage`：在哪个阶段触发（如 `EXECUTION`）
- `group`：同组专家并行执行，不同组串行执行
- `order_index`：同组内的执行顺序

默认编排链路：
```
Group 1: scene_expert  (景点先行，确定地理锚点)
Group 2: hotel_expert  (根据景点位置推荐住宿)
Group 3: food_expert   (根据酒店+景点位置推荐餐厅)
Group 4: route_expert  (综合以上规划路线)
```

---

## Skill 开发

继承 `BaseSkill` 并实现 `execute` 方法：

```python
from skills.base import BaseSkill

class MySkill(BaseSkill):
    name = "my_skill"
    description = "My custom skill"
    parameters = {
        "query": {"type": "string", "description": "Search query", "required": True}
    }

    def execute(self, query: str) -> dict:
        return {"result": f"You searched for: {query}"}
```

将文件保存到 `skills/my_skill.py`，系统会自动发现并注册，LLM 即可在对话中调用。

---

## 注意事项

- **API Key 安全**：请勿将 API Key 提交到代码仓库，`config.yaml` 已加入 `.gitignore`
- **长上下文**：攻略生成需要较大的上下文窗口，建议使用支持 32K+ 的模型
- **PDF 导出**：需要安装 Google Chrome 或 Chromium（Mac 通常已预装）
- **数据库**：首次启动自动创建 SQLite 数据库并初始化默认数据，删除 `instance/app.db` 可重置

---

## License

MIT
