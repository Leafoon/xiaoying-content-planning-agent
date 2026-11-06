# 最终交付报告

## 已交付

- 统一 AgentRunner，多轮工具调用和基于观察的动态重规划。
- Mock 与 Real 两种模型客户端，共享工具、SQLite、步骤状态和 Trace。
- `search_materials`、`generate_script`、`estimate_cost`、`save_proposal` 四个工具。
- 预算、截止时间、缺失输入、失败/部分结果/超时、最大轮数和调用次数处理。
- task_id 与方案保存幂等，成功步骤持久化并可恢复。
- README、环境示例、六份文档、示例输入/输出/Trace 和 pytest 测试。

## 验证命令

```bash
python -m pip install -r requirements.txt
python -m src.main init-db
pytest -v
```

交付时应把命令输出中的通过、失败、跳过数量替换为本次真实执行值。本次开发期间 `pytest -q` 的实际结果是 24 passed，未使用 API Key，因此 Real 模式只完成客户端配置边界验证和共享引擎契约验证，未宣称真实服务端调用成功。

独立运行的五大场景结果为 `normal=COMPLETED`、`needs-info=NEEDS_INFO`、`tool-failure=COMPLETED`、`budget-replan=COMPLETED` 且最终成本为 8、`repeat=COMPLETED` 且两次 proposal ID 相同。

## 未完成事项

没有连接真实商业素材平台，这是需求中明确的本地合成数据边界。真实模型端到端结果依赖用户提供有效的 API Key 和模型服务，因此不在离线测试中伪造。

## Git 信息

目标目录当前不包含独立 Git 历史，未创建或推送远程提交。若后续纳入 Git，应在交付时填写实际分支和 commit SHA。
