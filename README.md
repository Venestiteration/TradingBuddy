# AI 投研助手

本仓库包含 AI 投研助手的产品材料、桌面端原型和一个可在本机运行的 MVP。MVP 的主流程是：添加 A 股标的 → 查看真实行情与事件 → 生成有证据引用的 AI 分析 → 继续追问 → 保存自己的投资判断。

## 当前内容

- `ai-investment-assistant-desktop.html`：桌面端主交互原型
- `ai-investment-assistant-evaluation.html`：评估方案可视化页面
- `AI投研助手MVP交互方案与PRD.md`：MVP 产品需求与交互方案
- `AI投研助手产品与交互方案说明.md`：产品定位、交互与责任边界
- `AI投研助手噪音过滤与分析可信度评估方案.md`：噪音过滤和分析可信度评估
- `AI投研助手产品定位上线评估方案.md`：上线评估指标与判定规则
- `docs/superpowers/specs/`：产品原型、研究档案、导览和本机 MVP 设计文档
- `docs/superpowers/plans/`：原型和交互实现计划
- `frontend/`：FastAPI 托管的本机 MVP 前端
- `app/`：FastAPI、SQLite、行情/事件/证据和 AI 服务
- `start.sh`：创建环境并启动本机服务
- `交付内容/`、`交付结果/`：历史交付版本
- `tests/prototype.test.mjs`：现有原型结构冒烟检查

## MVP 技术方向

本机 MVP 采用 FastAPI + 现有 HTML/CSS/JavaScript 原型 + SQLite。行情和技术指标复用个人项目 [A-Share-Data-Visualization](https://github.com/Venestiteration/A-Share-Data-Visualization) 中的 Python 代码，资讯与公告使用真实数据源，AI 使用 OpenAI API。

详细方案见：

[`docs/superpowers/specs/2026-09-12-ai-investment-assistant-local-mvp-design.md`](docs/superpowers/specs/2026-09-12-ai-investment-assistant-local-mvp-design.md)

## 本机 MVP 运行

需要 Python 3.9+。首次运行会创建 `.venv`、安装依赖并生成 `.env`：

```bash
./start.sh
```

然后打开 <http://127.0.0.1:8000>。编辑 `.env` 填写 `OPENAI_API_KEY` 和你有权限调用的 `OPENAI_MODEL` 后重启服务，才能使用真实 AI 分析；未配置模型时仍可查看行情、事件和证据，但分析会明确返回失败状态，不会生成替代结论。

也可以手动运行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

健康检查：<http://127.0.0.1:8000/api/health>。

## 演示主流程

1. 点击“添加标的”，输入 `600519` 或搜索股票名称。
2. 查看最新价、日线指标和近期事件；页面会显示数据时间、抓取时间及缓存降级状态。
3. 选择一条事件并点击“生成分析”。
4. 展开事实、推断、未知项和下一步核验；点击证据编号查看来源详情。
5. 在“继续追问”中询问事件与当前判断的关系。
6. 保存“我的判断”后重启服务，SQLite 会保留资产和判断版本。

公开行情、新闻和公告接口可能受网络、字段变化、限流和授权范围影响。缺少数据时页面保留可用内容并显示错误，不把缺失内容包装成事实。模型输出只用于研究信息整理，不构成投资建议；本项目不连接券商、不执行交易，也不提供买卖、仓位、目标价或交易时点建议。

## 说明

压缩包、环境变量、缓存、数据库和本地运行产物不会提交。根目录的 `ai-investment-assistant-desktop.html` 仍保留为历史静态原型；实际运行 MVP 使用 `frontend/`。
