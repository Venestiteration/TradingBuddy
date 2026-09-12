# AI 投研助手

本仓库保存 AI 投研助手的产品设计、交互原型、评估方案和本机 MVP 实现设计。

## 当前内容

- `ai-investment-assistant-desktop.html`：桌面端主交互原型
- `ai-investment-assistant-evaluation.html`：评估方案可视化页面
- `AI投研助手MVP交互方案与PRD.md`：MVP 产品需求与交互方案
- `AI投研助手产品与交互方案说明.md`：产品定位、交互与责任边界
- `AI投研助手噪音过滤与分析可信度评估方案.md`：噪音过滤和分析可信度评估
- `AI投研助手产品定位上线评估方案.md`：上线评估指标与判定规则
- `docs/superpowers/specs/`：产品原型、研究档案、导览和本机 MVP 设计文档
- `docs/superpowers/plans/`：原型和交互实现计划
- `交付内容/`、`交付结果/`：历史交付版本
- `tests/prototype.test.mjs`：现有原型结构冒烟检查

## MVP 技术方向

本机 MVP 采用 FastAPI + 现有 HTML/CSS/JavaScript 原型 + SQLite。行情和技术指标复用个人项目 [A-Share-Data-Visualization](https://github.com/Venestiteration/A-Share-Data-Visualization) 中的 Python 代码，资讯与公告使用真实数据源，AI 使用 OpenAI API。

详细方案见：

[`docs/superpowers/specs/2026-09-12-ai-investment-assistant-local-mvp-design.md`](docs/superpowers/specs/2026-09-12-ai-investment-assistant-local-mvp-design.md)

## 原型预览

直接在浏览器打开 `ai-investment-assistant-desktop.html` 即可查看当前静态交互原型。原型内的数据目前仅用于交互演示；真实数据和 AI 接入按 MVP 设计文档实施。

## 说明

当前目录还不是最终运行代码仓库，压缩包、环境变量、缓存、数据库和本地运行产物不会提交。

