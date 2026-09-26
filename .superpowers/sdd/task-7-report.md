# Task 7 Report: Overview Refresh and Evidence-Aware Research Compatibility

## 改动文件

- `app/routers/assets.py`
  - overview 进入时调用 `sync_public_dynamics`：普通 GET 使用 24 小时新鲜度判定，手动 refresh 传入 `force=True`。
  - 同步或本地动态读取异常只记录到 `errors.public_dynamics`，不阻断 snapshot/history。
  - 最近 90 天存在 canonical dynamics 时，overview 只输出聚合后公开动态，同时保留真实 primary evidence 作为兼容 `event_id`，并增加 `dynamic_id` 与 `source_count`。
  - canonical dynamics 为空时只保留现有 market-fact fallback。响应增加 `public_sync`。
- `app/routers/research.py`
  - `ResearchRequest` 增加可选 `dynamic_id`。
  - canonical 请求按 asset 边界加载该 dynamic 的全部关联 evidence；旧 `event_id` 路径保持不变。
- `app/routers/chat.py`
  - `ChatRequest` 增加可选 `dynamic_id`。
  - canonical 请求优先加载全部关联 evidence，并对跨标的 dynamic 返回 404；旧 `event_id` 逻辑保持不变。
- `tests/test_public_dynamics_research.py`
  - 新增 6 个集成测试，覆盖 research/chat 全证据上下文、跨标的拒绝、canonical overview 序列化、refresh 单次强制同步、同步失败降级以及 visitor-AI 不落库。

## TDD 记录

1. 先新建测试并执行 `python3 -m unittest tests/test_public_dynamics_research.py -v`。
   - 结果：预期失败；research 只传递一条 evidence，chat 忽略 `dynamic_id`，跨标的 dynamic 未拒绝，overview 还没有同步入口和 canonical 字段。
2. 实现最小路由集成后重跑同一命令。
   - 结果：6 tests passed。
3. 定向兼容回归：
   - `python3 -m unittest tests/test_public_dynamics_research.py tests/test_zhipu_compat.py -v`
   - 结果：16 tests passed。
4. 全量回归：
   - `python3 -m unittest discover -s tests -p 'test_*.py' -v`
   - 结果：98 tests passed。
5. 静态与差异校验：
   - `python3 -m py_compile app/routers/assets.py app/routers/research.py app/routers/chat.py tests/test_public_dynamics_research.py`
   - `git diff --check`
   - 结果：均通过。

## 提交

- `001f465313c7b4e0432490cd82737f6bd878ed1c` — `feat: ground research in aggregated dynamics`

## Concerns

- 简报中“将 canonical ID 写入 analyses/messages”与当前 `origin/main` 的 visitor-AI 隐私设计直接冲突。按任务上下文的明确要求，本实现保留 AI 结果不写入共享数据库的行为；测试明确锁定该兼容性。
- 工作树没有 `.venv/bin/python`，因此使用可用的 `python3`。执行时仅出现已有的 LibreSSL/urllib3 兼容警告和 SWIG 退弃警告，不影响测试结果。

## 用户决策记录（2026-09-26）

- 用户确认 visitor-AI 隐私边界优先：canonical `dynamic_id` 只用于当次 research/chat 请求上下文，不写入共享 `analyses`/`messages`。
- Task 7 计划与简报对应条款已同步修订，后续审查以修订后条款为准。
- 现有实现已遵守该边界，无需修改业务代码。
