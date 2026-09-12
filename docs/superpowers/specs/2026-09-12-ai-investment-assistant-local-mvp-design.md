# AI 投研助手本机可运行 MVP 设计

## 1. 目标与完成定义

本项目将当前文件夹中的桌面端产品原型改造成一个本机可运行的 AI 投研助手。产品保留“动态—对话—研究档案—证据”的交互主线，接入真实 A 股行情、真实新闻与公告、真实 OpenAI 模型调用，并在本地持久化用户主动添加的资产和投资判断。

MVP 只闭环一个核心场景：

> 用户添加 A 股标的 → 查看真实行情和近期事件 → 针对事件调用 AI 分析或追问 → 核验证据 → 保存或修改自己的投资判断。

满足以下条件即视为完成：

- 本机通过一个启动脚本运行，并可访问 `http://127.0.0.1:8000`；
- 页面中不再存在被当作真实内容展示的模拟行情、模拟事件或模拟来源；
- 支持搜索并添加任意沪深 A 股；
- 行情、新闻或公告至少来自一个实时可用的真实数据接口；
- 完成至少一次真实 OpenAI API 调用；
- AI 输出中的事实能够定位到本次提供给模型的真实证据；
- 网络或模型失败时不生成伪造结论；
- 自选、手动持仓标记和投资判断能在本地持久化；
- README 能指导另一位使用者配置 API Key 并运行产品。

## 2. 产品边界

### 2.1 MVP 包含

- 股票代码或名称搜索；
- 自选资产和手动持仓标记的添加、删除与切换；
- 真实日线行情、K 线、成交量、MA、MACD、RSI、KDJ 和 BOLL；
- 最近个股新闻与公司公告；
- 基于用户选中事件的真实 AI 分析；
- 基于当前资产、事件、证据和投资判断的连续追问；
- “已知事实、当前推断、尚不确定、下一步可核验”四层回答；
- 来源标题、发布时间、链接、摘要和引用关系；
- 用户投资判断的创建、修改和历史版本保留；
- 行情、资讯、公告或 AI 失败时的明确降级。

### 2.2 MVP 不包含

- 自动推送和常驻后台任务；
- 券商账户连接、真实持仓同步和用户登录系统；
- 买卖、仓位、目标价格或交易时点建议；
- 自动交易或跳转下单；
- 全市场扫描、选股策略和组合优化；
- Backtrader 回测；
- 逐笔成交 Excel 分析；
- Bear/Base/Bull 目标价估值；
- 研报全文、社交舆情和复杂事件聚类；
- 向量数据库、复杂 RAG 和生产级监控；
- 生产环境的数据授权、金融内容合规和多用户隔离。

## 3. 总体架构

采用本机单进程应用，FastAPI 同时提供静态前端与后端接口：

```text
浏览器
  └─ 现有 HTML/CSS/JavaScript 原型
       ├─ 标的切换与动态
       ├─ 对话输入与生成状态
       └─ 研究档案与证据抽屉
             │ HTTP / SSE
             ▼
FastAPI
  ├─ 资产与判断接口
  ├─ 行情与事件接口
  ├─ AI 分析与追问接口
  └─ 静态文件托管
             │
             ├─ SQLite：资产、判断、证据、分析和对话
             ├─ 腾讯 / 新浪 / AkShare：行情、新闻和公告
             └─ OpenAI Responses API：结构化分析
```

选择该架构的原因：

- 当前 HTML 原型已经包含完整的信息层级、详情抽屉、导览和交互反馈，直接改造比在 Streamlit 中重写更能保留产品完成度；
- 个人 GitHub 项目中的行情采集、字段标准化和技术指标均为 Python 代码，FastAPI 可以直接复用；
- 前后端使用简单 HTTP/SSE 接口，边界明确，不需要引入 React、Vue、Node 构建链或自定义 Streamlit 组件；
- SQLite 和单进程服务适合本机演示，部署、迁移和清理成本低。

## 4. 页面与交互改造

### 4.1 保留内容

以 `ai-investment-assistant-desktop.html` 为前端基础，保留：

- 顶部标的切换器；
- 以“动态”为主入口的对话页面；
- 底部输入区和快捷问题；
- 唯一的右侧详情面板；
- 研究档案中的“判断 / 数据 / 推断 / 来源”四类信息；
- 来源、关键数据与推断链的站内跳转；
- 键盘焦点、减少动态效果、减少透明度和增强对比度支持；
- 首次使用导览，但导览文案不再引用模拟状态。

### 4.2 删除内容

- `assets` 和 `researchData` 中的硬编码股票与分析；
- `buildMarketSeries()` 生成的模拟行情；
- “模拟新动态”按钮和定时触发逻辑；
- 通过正则匹配返回固定回答的 `resolveAnswer()`；
- 假流式文本、模拟来源及“模拟数据”标签；
- 与真实功能无关的演示定时器。

### 4.3 新页面状态

#### 无标的

展示产品边界、数据来源说明和“添加自选 / 录入持仓”入口，不展示泛市场资讯。

#### 有标的、数据加载中

展示当前股票名称和分阶段加载状态。行情、事件分别返回，不要求等待 AI。

#### 有标的、尚未分析

展示真实价格、更新时间、行情图和优先级最高的真实事件。提供“生成分析”按钮。AI 不因页面刷新自动调用。

#### 已生成分析

首屏显示结论、影响状态和关键事实；完整的推断、未知项和下一步核验项按需展开。研究档案中的推断和来源页签可核验该分析。

#### 数据或 AI 失败

保留最近一次有效数据并显示其抓取时间。没有历史缓存时显示原始错误类别和重试入口。AI 失败不影响行情、事件和原始来源的浏览。

## 5. 真实数据设计

### 5.1 数据源

| 数据 | 首选来源 | 降级来源 | 更新策略 |
| --- | --- | --- | --- |
| 股票清单 | AkShare `stock_info_a_code_name` | SQLite 中最近成功清单 | 缓存 24 小时 |
| 实时快照 | 腾讯行情接口 | 最近一根日线 / 最近缓存 | 缓存 60 秒 |
| 历史日线 | 腾讯前复权日线 | AkShare `stock_zh_a_hist`，必要时新浪 | 缓存 30 分钟 |
| 个股新闻 | AkShare `stock_news_em` | 最近缓存 | 缓存 10 分钟 |
| 公司公告 | AkShare `stock_zh_a_disclosure_report_cninfo` | 最近缓存 | 缓存 10 分钟 |

所有外部请求必须设置连接和读取超时，并采用最多三次的有限重试。失败后不得长时间阻塞页面。

### 5.2 标准行情结构

后端统一输出：

```text
date, open, high, low, close, volume, amount,
MA5, MA10, MA20, MA60,
MACD_DIF, MACD_DEA, MACD,
RSI, KDJ_K, KDJ_D, KDJ_J,
BOLL_UPPER, BOLL_MID, BOLL_LOWER
```

数值转换、日期排序、无效行删除和中文字段映射在服务层完成，前端不处理上游字段差异。

### 5.3 证据结构

新闻、公告和行情事实统一为证据对象：

```text
evidence_id
stock_code
source_type        # market / announcement / news
source_level       # primary / secondary
title
excerpt
published_at
source_url
fetched_at
content_status     # full / excerpt / title_only
```

`content_status` 明确告诉 AI 和界面当前拥有的是正文、摘要还是标题。只有标题时，不允许模型将标题之外的内容描述为事实。

### 5.4 事件去重与排序

MVP 使用确定性规则，不由 AI 决定首页事件：

1. 按规范化标题和链接去重；
2. 公司正式公告高于新闻；
3. 财报、业绩、经营、风险提示等高相关关键词获得更高优先级；
4. 发布时间越近，排序越高；
5. 行情出现明显变化但没有高质量事件时，生成一条只描述行情事实的事件；
6. 没有足够证据时明确显示“未发现可确认的原因”，不生成唯一归因。

## 6. AI 分析设计

### 6.1 调用时机

仅在以下操作中调用模型：

- 用户点击“生成分析”；
- 用户发送自由问题；
- 用户点击需要生成回答的快捷问题。

切换标的、刷新页面和打开研究档案不会自动产生模型费用。相同事件、相同证据版本和相同判断版本的首轮分析可以直接使用 SQLite 缓存。

### 6.2 模型输入

后端只提交完成当前任务需要的上下文：

- 股票代码、名称和数据时间；
- 最新行情与选定技术指标；
- 当前选中的事件；
- 事件对应的证据对象及其 `evidence_id`；
- 用户已确认的投资判断与版本号；
- 当前标的最近若干轮对话；
- 产品边界和结构化输出要求。

模型不直接访问 SQLite，不接触其他标的上下文，也不自行执行交易或修改用户判断。

### 6.3 结构化输出

模型通过 JSON Schema 返回：

```text
conclusion
impact_state        # unaffected / watch / may_affect / insufficient
facts[]             # claim + evidence_ids[]
inferences[]        # claim + evidence_ids[] + uncertainty
unknowns[]
next_checks[]
safety_boundary
```

前端中文状态映射为“暂未影响、值得留意、可能影响原判断、信息不足”。

### 6.4 输出校验

后端返回前执行以下检查：

1. JSON 符合 Schema；
2. 每个事实至少引用一个本次输入中的 `evidence_id`；
3. 删除不存在的证据编号；
4. 无有效引用的事实不得进入“已知事实”；
5. 输入仅含标题时，不接受正文级细节；
6. 涉及买卖、仓位、目标价或交易时点的指令改为条件化分析；
7. 证据不足或冲突时，`impact_state` 降级为 `insufficient`。

校验失败时允许重试一次结构化生成；再次失败则展示“本次分析未通过证据校验”，同时保留原始资料入口。

### 6.5 生成状态

`POST /api/research/stream` 和 `POST /api/chat/stream` 通过 SSE 返回有限状态：

```text
context_ready → model_running → validating → completed / failed
```

结构化结果在 `completed` 事件一次性返回。MVP 不要求逐 token 解析半成品 JSON；界面仍能展示真实调用进度，而不会把客户端动画伪装成模型输出。

## 7. 本地数据模型

SQLite 至少包含以下表：

### assets

```text
id, stock_code, stock_name, asset_type, quantity, cost_price,
notifications_enabled, created_at, updated_at
```

`asset_type` 仅为 `watchlist` 或 `holding`。数量和成本均为可选字段，不参与交易建议。

### theses

```text
id, asset_id, version, core_thesis, watch_variables,
invalid_conditions, status, created_at
```

每次确认修改都插入新版本，不覆盖历史记录。

### evidence

保存标准证据对象、原始来源字段和抓取时间，用于引用核验和失败降级。

### analyses

保存事件、证据版本、判断版本、模型名称、结构化结果、校验状态和生成时间。

### messages

保存当前标的的用户问题、AI 结构化回答、关联事件和创建时间。MVP 不实现跨用户隔离。

## 8. API 边界

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/health` | 启动与配置状态检查 |
| `GET /api/stocks/search?q=` | 按代码或名称搜索股票 |
| `GET /api/assets` | 获取本地资产列表 |
| `POST /api/assets` | 添加自选或手动持仓 |
| `PATCH /api/assets/{id}` | 修改类型、数量、成本或提醒状态 |
| `DELETE /api/assets/{id}` | 删除本地资产 |
| `GET /api/assets/{id}/overview` | 获取行情、指标、事件和最近分析 |
| `POST /api/assets/{id}/refresh` | 主动刷新真实数据 |
| `GET /api/assets/{id}/theses` | 获取当前判断与版本历史 |
| `POST /api/assets/{id}/theses` | 保存新的已确认判断版本 |
| `POST /api/research/stream` | 对选中事件生成首轮分析 |
| `POST /api/chat/stream` | 在当前证据范围内继续追问 |
| `GET /api/evidence/{id}` | 获取证据详情与来源链接 |

接口返回统一包含 `data_time`、`fetched_at` 和 `stale`，让界面区分数据发生时间、获取时间和是否为缓存。

## 9. 建议文件结构

```text
ai-investment-assistant-mvp/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── schemas.py
│   ├── routers/
│   │   ├── assets.py
│   │   ├── research.py
│   │   └── chat.py
│   └── services/
│       ├── market.py
│       ├── events.py
│       ├── evidence.py
│       └── ai.py
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── prompts/
│   └── grounded_analysis.md
├── data/
│   └── assistant.db
├── tests/
│   └── smoke_test.py
├── .env.example
├── requirements.txt
├── start.sh
└── README.md
```

`data/assistant.db` 在首次启动时创建，不提交真实用户数据。仓库只保留空目录占位或初始化逻辑。

## 10. 旧项目复用计划

来源项目：[A-Share-Data-Visualization](https://github.com/Venestiteration/A-Share-Data-Visualization)。

### 10.1 直接迁移或小幅改造

| 原模块 | 复用内容 | 调整 |
| --- | --- | --- |
| `config.py` | `Settings`、`COLUMN_ALIASES`、`normalize_columns` | 改为 MVP 环境变量与缓存目录 |
| `stock_screener.py` | `MarketCollector._market_code` | 作为股票代码规范化工具 |
| `stock_screener.py` | `_public_stock_history`、`stock_history` | 统一超时、有限重试、异常类型和缓存 |
| `stock_screener.py` | `stock_snapshot` | 补充字段校验及缓存时间 |
| `single_stock_service.py` | `_normalize_history` | 保留字段与日期清洗逻辑 |
| `single_stock_service.py` | `technical_indicators` | 作为行情服务的纯计算函数 |
| `single_stock_service.py` | `market_analysis` 的编排思路 | 改为返回 API Schema，不返回 Streamlit 对象 |

### 10.2 不复用

- `app.py` 和 `single_stock_page.py` 的 Streamlit 页面；
- `CategoryScreener`、`filter.py`、`strategy.py` 和 `condition.py`；
- `backtest.py`；
- 逐笔成交 Excel 逻辑；
- `ReportBuilder`；
- `ValuationSummarizer` 与三情景目标价；
- 原 `LLMResearcher` 及长篇估值提示词。

不复用的原因是这些模块不属于当前闭环，或会让模型在证据不足时讨论估值和目标价格，与已确认的产品边界冲突。

## 11. 开发顺序

### 阶段 1：可启动骨架

- 创建 FastAPI 应用、配置加载和 SQLite 初始化；
- 拆分现有单文件 HTML 为 `index.html`、`styles.css` 和 `app.js`；
- 由 FastAPI 托管前端；
- 提供 `/api/health`、`.env.example` 和 `start.sh`；
- 验证一个命令可启动并打开现有界面。

### 阶段 2：真实行情与资产管理

- 迁移股票清单、行情快照、历史行情、字段标准化和指标计算；
- 实现股票搜索、添加、删除、类型修改和标的切换；
- 用 API 返回的 OHLCV 替换前端模拟行情；
- 完成行情缓存、超时和最近有效数据降级。

### 阶段 3：真实事件与证据

- 接入个股新闻和巨潮公告；
- 实现证据标准化、内容状态、去重和规则排序；
- 在首屏动态和来源面板中使用真实事件；
- 完成来源链接、时间和缓存状态展示。

### 阶段 4：真实 AI 分析与追问

- 定义分析 JSON Schema 和证据约束 Prompt；
- 实现 Responses API 调用、SSE 状态和一次重试；
- 校验证据引用、交易边界和信息不足状态；
- 将结构化结果映射到现有回答层级与推断链；
- 实现基于当前资产、事件、证据和判断的连续追问。

### 阶段 5：持久化与交付收尾

- 完成投资判断版本、分析缓存和对话记录；
- 清除剩余模拟内容和演示定时器；
- 完成空状态、错误状态和最后有效数据展示；
- 编写 README、演示脚本和最小冒烟检查。

## 12. 最低验证方案

不建设完整测试体系，只保留四项自动冒烟验证：

1. 服务启动后首页与 `/api/health` 可访问；
2. 输入 `600519` 能获得非空真实日线、价格时间和至少一种真实事件来源；
3. 发起一次真实 AI 分析后，输出符合 Schema，所有事实引用的证据编号都存在；
4. 重启服务后，自选标的和用户判断仍然存在。

再人工完成一次主流程：

> 添加贵州茅台 → 查看行情和近期事件 → 生成 AI 分析 → 展开来源 → 追问“这会影响我的判断吗” → 保存判断 → 重启后确认数据仍存在。

测试不要求覆盖全市场、所有 AkShare 异常、浏览器矩阵、压力测试、视觉回归或模型回答语义的全面自动评分。

## 13. 错误处理与降级

| 异常 | MVP 行为 |
| --- | --- |
| 股票清单失败 | 使用本地缓存；仍允许输入六位代码 |
| 实时行情失败 | 显示最近日线或最近缓存，并标记时间 |
| 历史行情失败 | 保留快照与事件，图表显示重试入口 |
| 新闻失败 | 展示公告；两者都失败时只展示行情事实 |
| 公告失败 | 展示新闻并明确来源等级 |
| 仅有标题 | 标记 `title_only`，AI 不得扩写未提供细节 |
| 来源冲突 | 并列保留，输出状态为“信息不足” |
| AI 超时或限额 | 展示原始数据和来源，不生成替代结论 |
| AI Schema 不合法 | 重试一次；再次失败则返回校验失败状态 |
| 引用编号无效 | 删除无效引用；无引用事实不进入事实层 |
| 用户询问买卖 | 转为证据、条件和待核验项，不输出指令 |

## 14. 配置与运行

`.env.example` 至少包含：

```text
OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_BASE_URL=
APP_HOST=127.0.0.1
APP_PORT=8000
DATABASE_PATH=data/assistant.db
REQUEST_TIMEOUT_SECONDS=12
```

`OPENAI_BASE_URL` 为可选兼容配置；默认使用 OpenAI 官方接口。`OPENAI_MODEL` 由使用者显式配置，避免把账户可能无权访问的模型写死在代码中。

预期运行方式：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./start.sh
```

`start.sh` 只启动本机 FastAPI，不执行后台抓取、全市场扫描或模型预热。

## 15. 风险与明确限制

- AkShare、腾讯、新浪和巨潮均为外部数据依赖，接口字段、限流或可用性可能变化；MVP 通过字段标准化、超时、缓存和降级降低影响，但不能提供生产级 SLA；
- 免费公开数据不等同于获得生产环境的数据展示和商业使用授权；
- 个股新闻的正文覆盖可能不完整，`content_status` 必须如实展示；
- OpenAI 调用需要用户自己的有效 API Key、可用模型权限和余额；
- 模型输出经过结构与引用检查，但不能替代专业投研或合规审核；
- 本机单用户 SQLite 不提供账号隔离、加密存储、云同步和远程访问；
- 产品只用于研究信息整理，不构成投资建议。

这些限制不阻碍本机作品演示，但必须在页面与 README 中明确写出。

