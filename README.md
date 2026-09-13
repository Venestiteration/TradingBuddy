# TradingBuddy

本地优先的 AI 投研助手 MVP。用户可添加 A 股标的，查看真实行情与公开事件，基于可回溯证据生成研究分析、继续追问，并维护自己的投资判断。

项目只提供研究信息整理，不连接券商、不执行交易，也不输出买卖、仓位、目标价或交易时点建议。

## 仓库结构

- `app/`：FastAPI、SQLite、本地资产管理、行情、事件、证据与 AI 分析服务。
- `frontend/`：由 FastAPI 托管的原生 HTML/CSS/JavaScript 界面。
- `prompts/`：有证据约束的模型提示词。
- `tests/`：智谱/OpenAI 兼容接口的最小回归测试。
- `docs/product/`：产品与交互说明、MVP PRD。
- `docs/technical/`：本机 MVP 的技术设计与接口约定。

开发前建议先阅读：

- [产品与交互说明](docs/product/product-and-interaction.md)
- [MVP PRD](docs/product/mvp-prd.md)
- [本机 MVP 技术设计](docs/technical/local-mvp-design.md)

## 本地运行

需要 Python 3.9+。首次启动会创建虚拟环境、安装依赖并生成 `.env`：

```bash
./start.sh
```

打开 <http://127.0.0.1:8000>。行情和事件可在未配置模型时使用；AI 分析需要在 `.env` 配置模型后重启服务：

```env
OPENAI_API_KEY=<your-api-key>
OPENAI_MODEL=glm-5.3
OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
```

`OPENAI_BASE_URL` 留空时使用 OpenAI；填写智谱地址时，服务会自动使用其 Chat Completions 兼容接口。

## 下一阶段 MVP 能力

- 研究重要性时间线：按交易日汇总公开动态、上下游、行情和跨资产四类重要性。折线高度表示等权综合分，节点颜色表示当日主导类别。分数代表研究注意力，不代表涨跌或买卖建议。
- 判断沉淀：可将上次确认版本之后的对话与证据整理为草稿。AI 只提出字段级建议，用户确认后才创建带日期的新版本，历史版本不会被覆盖。

时间线首次打开会基于本地已有行情和证据生成最近 30 个交易日数据。若 8000 端口已被占用，可运行 `PORT=8010 ./start.sh`。

## 最小验证

```bash
python3 -m unittest tests/test_zhipu_compat.py -v
curl http://127.0.0.1:8000/api/health
```

公开行情、新闻和公告接口可能受网络、字段变化、限流和授权范围影响。页面会展示数据时间、抓取时间和缓存状态；数据或模型不可用时不会用模拟内容替代真实结果。
