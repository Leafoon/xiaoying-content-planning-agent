# 评估方案与结果

验收覆盖以下场景。

| 场景 | 预期 | 覆盖 |
| --- | --- | --- |
| 完整输入 | COMPLETED，方案持久化 | `test_normal_completion` |
| 缺预算或截止时间 | NEEDS_INFO，不调用工具 | `test_missing_budget_or_deadline_is_needs_info` |
| 一次工具失败 | 记录 FAILED，调整检索并完成 | `test_failure_replans_and_keeps_failed_step` |
| 脚本失败 | 改用 fast 方案后完成 | `test_script_failure_can_switch_generation_variant` |
| 部分成功 | 保留 partial 标记并继续执行 | `test_partial_material_result_is_preserved_in_trace` |
| 模型参数绕过约束 | 引擎按真实观察重算并拒绝超预算保存 | `test_engine_rejects_model_attempt_to_save_over_budget` |
| 初始成本 12 超预算 10 | 切换 low_cost，成本 8 后保存 | `test_budget_overrun_switches_to_low_cost` |
| 重复 task_id | 复用同一 proposal_id | `test_idempotent_repeat_does_not_create_second_proposal` |
| 所有替代方案超预算 | INCOMPLETE，不保存 | `test_all_alternatives_over_budget_is_incomplete` |
| 截止时间不足 | 尝试 fast，仍不可行则停止 | `test_deadline_replans_to_fast_then_stops_if_still_impossible` |
| 最大轮数 | 明确 INCOMPLETE | `test_max_steps_is_explicit` |
| 最大工具调用数 | 明确 INCOMPLETE | `test_max_tool_calls_is_explicit` |
| 连续失败、保存续跑和工具超时 | 停止并保留已完成结果，超时不阻塞引擎 | `test_continuous_failure_stops_with_explicit_incomplete`, `test_failed_save_can_resume_without_repeating_successful_work`, `test_tool_timeout_is_recorded_without_waiting_for_tool` |
| 请求续填、请求冲突、崩溃恢复和并发保存 | 只允许补全缺失信息，拒绝业务冲突，恢复 stale RUNNING，保存原子幂等 | `test_missing_info_task_can_be_completed_later`, `test_same_task_id_with_different_business_request_is_rejected`, `test_stale_running_step_is_recovered`, `test_concurrent_save_is_atomic` |

最近一次本地执行命令是 `pytest -q`，结果为 24 passed。每次交付前应重新执行要求中的 `python -m src.main init-db` 与 `pytest -v`，最终报告只记录实际输出。
