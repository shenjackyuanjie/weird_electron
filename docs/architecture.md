# 架构、数据流与执行语义

[文档首页](README.md) · [协议](contracts.md) · [API](api.md)

## 模块边界

| 模块 | 职责 | 不做什么 |
|---|---|---|
| `power_engine/contracts.py` | Pydantic 模型、输入复验、内容指纹 | 不替代设备授权或安全策略 |
| `battery.py` | SOC 积分、能量/铭牌/降额功率交集 | 不模拟温度、老化或频率 |
| `power_flow.py` | 每次构建两母线网络，真实 AC 潮流 | 不推进时间、不执行设备命令 |
| `optimizer.py` | 两种充放电模式的 LP、反馈预算 | 不批准或执行自己的候选 |
| `baseline.py` | 固定顺序调度；复用约束预算辅助函数 | 不调用优化求解器，不宣称经济最优 |
| `validator.py` | 硬规则检查与独立 AC 复算 | 不信任 `expected_grid_kw` 或外部通过标记 |
| `api.py` | 三个计算工具的 JSON 适配 | 不是 HTTP/MCP 服务，没有执行远端入口 |
| `simulator/scenarios.py` | 初始状态、A/B/C 和正常参数 | 不自动产出恢复答案 |
| `simulator/simulator.py` | 状态、待执行命令、回执、时间推进 | 不提供真实时钟线程或跨进程持久化 |
| `controller.py` | 策略→校验→有限重规划→提交→step | 不包含 Agent 或云端工作流 |
| `metrics.py` | 对实际执行证据进行独立审计 | 不证明模型外真实电网安全 |
| `cli.py` | Demo、配对实验、Schema、文件输出 | 不提供 Dashboard 或设备遥测服务 |

`baseline` 当前导入 `optimizer.planning_inputs` 复用损耗预算和边界，因此导入层面仍需要 SciPy；“不调用求解器”不等于“可以卸载 SciPy”。

## 一个完整周期

读取不可变 state 快照后，策略提出 `DispatchPlan`，计划绑定该快照的 SHA-256。Validator 先拒绝关键负荷削减、功率/SOC 越界、旧状态等硬错误；只有硬规则全部通过，才调用真实 AC 潮流。

若被拒绝，`control_step` 默认传回 `ValidationResult` 再规划一次。缺依赖、计算失败、状态失效和不支持的孤岛等错误直接停止，不盲目重试。默认总共最多两次候选，不是两次重规划。

候选通过后，`apply_action` **针对 Simulator 当前状态重新调用 Validator**。这个结果与前一次候选校验是两个不同的调用，实际执行回执保留第二个结果。它只接收命令，并不立即改变物理量。

`step` 检查状态/配置仍匹配批准时的内容，使用已批准的潮流结果和 SOC 预测推进一个完整区间。它不再次运行 AC 求解，也不延长原方案的有效期。随后实验运行器对实际状态、方案和回执进行独立审计。

## 命令状态机

```text
空闲 --apply_action(安全且新 ID)--> accepted / pending
pending --step(指纹和时长匹配)--> applied / 空闲
pending --cancel_pending_action--> cancelled / 空闲
pending --trigger_scenario------> cancelled / 新事故状态
任意状态 --reset---------------> 新 run_id / 空闲 / 清空回执
```

`apply_action` 失败不会创建 accepted 回执。`step` 参数错误、状态/配置失效时不会推进时间，也不会自动丢弃 pending；可检查错误、取消命令，再用新状态重新规划。

| 情况 | 当前行为 |
|---|---|
| 同 `plan_id`、同全部内容再次提交 | 返回该 ID 当前回执；可能已 applied 或 cancelled，不会重复执行 |
| 同 `plan_id`、内容不同 | `IDEMPOTENCY_CONFLICT` |
| 已有 pending，又提交另一个新 ID | `ACTION_PENDING` |
| 没有 pending 调用 step | `NO_PENDING_ACTION` |
| 显式 step 时长不同于方案 | `DURATION_MISMATCH` |
| 接收后更改 config，再调用 step | `STALE_CONFIG`；先取消，重新规划 |
| reset 后提交旧 plan | 新 run_id 使状态指纹改变，不能重放 |

取消后的 ID 不能重新作为新命令使用；生成新的 `plan_id`。`get_receipt` 只能查询当前实例、当前 reset 周期内的记录；返回 `None` 不证明外部设备从未执行过。

## 时间与状态

`reset()` 恢复初始配置、SOC 和模拟时间，生成新 run_id；`trigger_scenario("normal")` 只恢复场景参数，保留时间/SOC。事故触发与执行均增加 `state_revision`。

状态默认使用固定模拟时间起点 `2026-10-14T00:00:00+09:00`。它用于可重复软件实验，不是实时设备时间戳。只有成功 step 推进时间。`timestamp` 始终带时区；日志另以 perf_counter 记录本地计算耗时，二者不能相减混算。

控制期间外部条件在区间内恒定。模拟器不会在“没有安全方案”时自行估计停电能量、继续放电或模拟频率崩溃。

## 并发、信任与部署边界

实例级 `RLock` 串行化 public 操作，保护 state/pending/receipts 的一致性。整个“读状态→求解→执行”的多次调用不是一个整体锁事务；并发控制器可能得到 `STALE_STATE` 或 `ACTION_PENDING`，上层要重新读取，而不是绕过检查。

锁不跨进程、不跨机器，进程重启后不保留命令 ID。`state`/`config` 必须由服务端可信来源提供；远端提交的通过标记、指纹或 JSON 自身都不能授予执行权。SHA-256 只是内容绑定，不是数字签名。

运行模型是单周期内的准稳态一致性；没有网络传输、设备部分执行、MQTT 重投递恢复、认证与权限管理。对接责任和验收条件见[交接](handoff.md)。
