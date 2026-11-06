# xiaoying-content-planning-agent

小影校招内容任务规划 Agent。它接收活动主题、预算和截止时间，由模型在每一轮观察工具结果后选择下一动作。离线默认使用 Mock 模型，Real 模式使用 OpenAI 官方 SDK 的 Tool Calling。两种模式共享 `AgentRunner`、四个工具、SQLite 数据库和 Trace。

## 安装

```bash
cd "内容任务规划 Agent"
python -m pip install -r requirements.txt
```

建议使用 Python 3.11 或更高版本。复制 `.env.example` 为 `.env` 后按需设置数据库路径和模型参数。

## 初始化和运行

```bash
python -m src.main init-db
python -m src.main plan \
  --task-id demo-001 \
  --topic "新品发布" \
  --budget 10 \
  --deadline "2026-11-06T18:00:00+08:00" \
  --variant high_cost
python -m src.main show-trace demo-001
```

`--variant high_cost` 会先产生 12 个模拟单位的方案。当预算为 10 时，Mock 模型观察估算结果并改用 `low_cost`，最终成本为 8。`--fail-material-once` 可注入一次素材检索失败。

`--budget` 和 `--deadline` 在 CLI 中是可选的。缺少任一字段时，命令会返回 `NEEDS_INFO` 并列出缺失字段，不会执行工具。

## Real 模式

在 `.env` 中设置 `AGENT_MODE=real`、`OPENAI_API_KEY` 和可选的 `OPENAI_MODEL` 或 `OPENAI_BASE_URL`。真实客户端只负责返回 Tool Calling 决策，工具仍使用本地合成数据。没有 API Key 时保持 Mock 模式即可，不能把 Mock Trace 当作真实模型结果。

## 测试

```bash
python -m src.main init-db
pytest -v
```

测试使用临时 SQLite，不访问商业素材平台或网络。覆盖正常完成、信息不足、一次失败后的重规划、预算替代方案、截止时间不足、全部超预算、最大决策轮数、SQLite 持久化、Trace 和 Real 模式配置边界。

## 状态和持久化

任务状态包括 `PLANNING`、`RUNNING`、`REPLANNING`、`NEEDS_INFO`、`COMPLETED`、`FAILED`、`INCOMPLETE`。步骤状态包括 `PENDING`、`RUNNING`、`SUCCESS`、`FAILED`、`SKIPPED`。`tasks`、`steps`、`tool_results`、`traces` 和 `proposals` 表均落在 SQLite。`task_id` 与方案有唯一约束，重复执行已完成任务会复用原方案。

## 目录

- `src/agent` 统一动态执行循环、Mock/Real 客户端和 Trace
- `src/tools` 四个结构化工具及注册表
- `src/repositories` SQLite 事务和幂等保存
- `tests` 自动化验收和边界测试
- `examples` 可复现输入、输出与 Trace
- `docs` 需求、方案、评估、AI 使用、复盘和交付报告
