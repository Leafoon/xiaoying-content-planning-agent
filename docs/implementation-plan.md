# 内容任务规划 Agent 开发执行计划

## 1. 需求拆解与核心业务流程

系统接收活动主题、预算、截止时间及可选偏好，先校验必填约束，随后由模型驱动的执行循环规划并调用 `search_materials`、`generate_script`、`estimate_cost`、`save_proposal`。每轮把工具结果作为观察反馈给模型，由模型动态选择下一动作、替换方案、重试或停止。预算和截止时间由工具结果及执行引擎共同校验，最终返回 COMPLETED、NEEDS_INFO、INCOMPLETE 或 FAILED，并保留已完成步骤。

## 2. 技术选型及理由

- Python 3.11，使用标准库 `sqlite3`、`datetime`、`json` 保证离线可运行。
- Pydantic v2 做输入输出校验和可序列化结构。
- OpenAI 官方 SDK 仅在 Real 模式按需导入，使用 Chat Completions Tool Calling，避免离线测试依赖 API。
- Typer 提供 CLI，pytest 覆盖验收场景和边界。
- SQLite 采用事务、唯一索引和 WAL，持久化任务、步骤、工具结果、Trace、方案。

## 3. 项目目录结构

```text
src/
  agent/       执行引擎、模型客户端、工具注册、Trace
  models/      Pydantic schema 与状态枚举
  tools/       四类业务工具
  repositories/ SQLite 数据访问
  services/    计划/约束/执行协调服务
  mock/        可测试的动态 Mock 决策器
  main.py      Typer CLI
 data/         本地合成素材与配置
 tests/        单元、集成、五大验收及边界测试
 examples/     输入、输出、Trace 示例
 docs/         计划、需求、方案、评估、AI 使用、复盘、交付报告
```

## 4. Agent 架构与动态决策机制

`AgentRunner` 使用统一循环：创建或恢复任务 → 从模型客户端获取 `Decision` → 校验依赖、预算、截止时间及调用上限 → 执行注册工具 → 持久化步骤与观察 → 将摘要回传模型。Mock 模型是显式策略实现，只根据当前状态与工具结果选择动作，支持替代方案和失败调整。Real 模式将相同状态序列化到消息并把工具 schema 交给模型，解析模型返回的 tool call 或最终 JSON。引擎不写死完整调用顺序，最多限制决策轮数、工具次数和单次工具超时。

执行引擎会把模型参数与已成功工具结果进行归一化和交叉校验。成本估算使用真实素材和脚本结果，保存前再次检查预算与截止时间，避免模型通过伪造参数绕过业务约束。任务请求与 `task_id` 绑定，续填只允许补全 `NEEDS_INFO` 的缺失字段。

## 5. 工具设计及输入输出

- `search_materials(topic, preferences, variant)` 从 `data/materials.json` 查找素材，返回素材列表、成本、耗时，支持 `fail_once`/`force_fail` 注入。
- `generate_script(topic, material_ids, variant)` 生成脚本草案，返回方案、成本、耗时和素材引用。
- `estimate_cost(topic, material_ids, variant, script_cost)` 汇总成本、剩余预算、总耗时和是否满足约束。
- `save_proposal(task_id, proposal)` 在事务和唯一 task_id 约束下保存方案，重复保存返回原 proposal_id。

所有工具返回结构化 `ToolResult`，失败与部分成功包含 error、partial、retryable 字段。

## 6. 数据存储与任务状态管理

SQLite 表包括 `tasks`、`steps`、`tool_results`、`traces`、`proposals`。任务和方案以 `task_id` 唯一，步骤以 `(task_id, step_id)` 唯一。每次状态变更和工具结果使用事务写入。成功步骤在恢复或重规划时复用，失败步骤可续跑，禁止以失败覆盖既有成功记录。

## 7. 五大验收场景实现方案

1. 完整输入使用默认 Mock 策略完成检索、脚本、估算、保存。
2. 缺少预算或截止时间立即返回 NEEDS_INFO，数据库不执行工具。
3. `fail_once` 使第一次检索失败，Mock 观察失败后改用替代检索，保留失败记录和后续成功步骤。
4. 高成本 variant 产生 12 单位，预算 10 时 Mock 选择 low_cost variant 产生 8 并重新估算后保存。
5. 同一 `task_id` 由数据库唯一约束和已有完成任务恢复逻辑保证重复运行不重复创建任务或方案。

另外用短截止时间、极低预算、连续失败、`max_steps`/`max_tool_calls` 覆盖停止边界。

## 8. 测试方案及预期结果

pytest 测试 schema、工具、依赖、预算和时间约束、错误恢复、幂等、Trace、CLI。所有测试使用临时 SQLite 和 Mock，不依赖网络或 API Key。`pytest -v` 应全绿，Real 模式在无 key 时明确返回配置错误而不伪造成功。

## 9. 分阶段开发顺序

1. 创建目录、依赖、计划和数据模型。
2. 编写 SQLite repository、四类工具和服务层。
3. 实现 Mock/Real client、工具注册和 AgentRunner。
4. 加入动态重规划、约束、恢复、幂等和 Trace。
5. 实现 CLI、示例与五份正式文档。
6. 执行安装、初始化数据库、pytest、五大场景演示，按真实结果修复。

## 10. 每阶段完成标准

- 阶段 1：可导入 schema，计划文件存在，依赖可安装。
- 阶段 2：四工具可独立调用，SQLite 可初始化并读取状态。
- 阶段 3：Mock 完整闭环通过，Real 客户端可选导入。
- 阶段 4：预算/时间/失败/重试/幂等/最大步数测试通过，Trace 可审计。
- 阶段 5：README、`.env.example`、六份文档、examples 齐全，CLI 命令可运行。
- 阶段 6：执行要求中的三条命令及五大场景，交付报告只记录真实输出和未完成事项。
