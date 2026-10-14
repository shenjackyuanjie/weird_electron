# B 线接口协议 v0.1（待集成负责人冻结）

依据实施计划 §1.3、§2、§8.2。此文件先于字段修改更新；它是本次实现的协议草案，不声称 A/C 已同意。

## 单位与方向

- 功率 kW，容量 kWh，时长秒，SOC 0–1，电压 p.u.，频率 Hz。
- `battery_power_kw > 0` 为放电，负数为充电；进入 pandapower storage 时反号并除以 1000。
- `grid_power_kw > 0` 为从主网进口，负数为出口。
- `timestamp` 必须带时区；模拟时间与真实代码运行耗时分开。
- JSON 拒绝 NaN/Infinity、未知字段、负需求和不合法时长。普通 Python 类型转换采用 Pydantic 默认行为；不是 strict-mode 类型系统。
- 当前与预测 SOC 的运行边界统一采用 `SOC_TOL = 1e-10`（SOC 0–1 单位），由电池模块定义，优化器、固定规则和 Validator 共用。只容忍浮点误差，不扩大充放电能量额度、不裁剪或重写 SOC；超过容差仍拒绝。Schema 的绝对 `[0, 1]` 范围保持不变。

## 模型与职责

`MicrogridState`：当前观测。包含计划规定的核心字段，以及可用 PV、实际 PV、关键/普通负荷需求与供电、可削减上限、储能降额功率、PCC 进口/出口上限。`normal_shed_max_kw <= load_normal_kw`。未做潮流/刚注入事故时电压和 PCC 功率为 null，不能把 null 画成“正常”。`run_id` 每次 reset 改变；`state_revision` 在事故和执行时增加。

`DispatchPlan`：request_id、plan_id、完整状态 SHA-256 指纹、duration_seconds (0,300]、PV 实际设定、储能功率、普通削负荷、关键削负荷（只能为零），及可选 expected_grid_kw。后者是优化估计，不是主网功率命令；Validator 完全不依赖该估计。

`ValidationResult`：序列化键为 **pass**，Python 属性为 `passed`。包含输入状态、方案、配置指纹；predicted_soc；AC 结果；带 code/message/actual/limit 的 violated_rules。硬规则失败时不调用潮流。未收敛、非有限结果、缺依赖都拒绝。

`ExecutionReceipt`：accepted / applied / cancelled。收到事故会取消已接受但未执行的方案。相同 plan_id+内容重复调用返回原回执；同 ID 不同内容拒绝。reset 后旧方案因 run_id 不同不能重放。

`OptimizationResult`：optimal / feasible / infeasible / error。优化器的 optimal 仅指当前简化 LP；固定规则返回 feasible，不声称最优。无解返回 plan=null。AC 是否安全由 Validator 独立判定。

运行 `python -m simulator schemas` 获取字段级 JSON Schema。算法可接受对应 Pydantic 对象或字典，对外只传 JSON，不传 pandapowerNet。

## 时间与执行语义

`apply_action(plan)` 在**最新状态**独立复验，保存不可变方案与校验结果，仅返回 accepted，不推进时间。
`step()` 使用方案指定的整个 duration_seconds（默认 5 秒），原子更新功率/SOC/时间并返回 applied。显式传入不同 dt 拒绝。步骤前再次确认状态和配置指纹相同，因此不会换状态后沿用旧批准。
没有 pending 方案时 step 返回 NO_PENDING_ACTION，不伪装系统依然稳定运行。调用者需要每周期读取状态、重规划、校验与提交；真实实时调度器和故障保护不是本版本的功能。

哈希是内容绑定，不是签名/权限验证。当前 idempotency 记录仅在单个进程内；公开服务接入前由 A/C 增加认证、持久化、跨进程串行化和设备授权。不可将“用户传入的 config/state”当成可信设备状态。

## 算法和 JSON 入口

- `run_power_flow(state, plan, config=None)` → PowerFlowResult
- `optimize_dispatch(state, config=None, duration_seconds=None, feedback=None)` → OptimizationResult
- `validate_plan(state, plan, config=None)` → ValidationResult
- `fixed_rule_dispatch(...)` → OptimizationResult（相同规划输入）
- `invoke(tool, payload, config=None)` → `{ok, request_id, result}` 或 `{ok:false, request_id, error_code, message}`

`invoke` 接收已解码的 JSON，顶层必须是对象。`null`、数组、字符串、数值或布尔值均返回结构化 `INVALID_INPUT`，并生成兜底 request_id，不调用算法；有效对象仍按原约定透传 request_id。JSON 文本解码由上层 MCP/HTTP 负责。

config 是部署方的可信配置，不在 invoke 的远端 payload 中开放。`ok=true` 不等于通过安全校验。request_id 在优化接口传入时贯穿生成的 plan 及后续验证/执行；调用其他工具时应复用 plan.request_id。

## 错误码

硬规则：STALE_STATE、CURRENT_SOC_LIMIT、SOC_MIN、SOC_MAX、ESS_DISCHARGE_LIMIT、ESS_CHARGE_LIMIT、CRITICAL_LOAD_SHED、NORMAL_SHED_LIMIT、PV_AVAILABILITY。
AC：GRID_IMPORT_LIMIT、GRID_EXPORT_LIMIT、VOLTAGE_LOW、VOLTAGE_HIGH、LINE_OVERLOAD、POWER_BALANCE、POWER_FLOW_FAILED、DEPENDENCY_UNAVAILABLE、UNSUPPORTED_ISLAND_MODE。
规划/执行：NO_FEASIBLE_DISPATCH、OPTIMIZER_FAILED、STALE_FEEDBACK、UNSAFE_PLAN、ACTION_PENDING、NO_PENDING_ACTION、DURATION_MISMATCH、STALE_CONFIG、IDEMPOTENCY_CONFLICT。
适配器：INVALID_INPUT、UNKNOWN_TOOL。时间区间结束后仍需要设备级保护，此协议不作生产安全保证。

## 尚未由 B 线定义的集成对象

TelemetryEvent 外层设备封包、GridEvent、AgentFinding、IoTDA 命令回执映射，需要 A/C 与集成负责人按实施计划共同冻结。本仓库没有伪造这些云端实现。

## 第二轮审查补充（2026-10-14，仍为待冻结草案）

- `duration_seconds` / `step_seconds` 必须是 JSON 数值，拒绝布尔值、字符串、容器和非有限数；范围仍为 `(0,300]`。规划接口的 `duration_seconds=null` 或省略使用配置默认值。
- `request_id` 和 `plan_id` 为 1–128 字符且不能全为空白的字符串，拒绝把对象/数值强制转成 ID。未传顶层 request_id 时，优化调用生成 UUID，验证/潮流调用继承 plan.request_id；显式传入冲突 ID 返回 INVALID_INPUT。格式不合法时错误响应使用新生成的兜底 UUID。
- `PowerFlowResult.converged=true` 必须同时包含全部电气量，且 min_voltage <= pcc_voltage <= max_voltage，不能带 error_code。Validator 对缺字段/非法潮流结果返回 INVALID_POWER_FLOW_RESULT，不把空结果视为通过。
- 执行回执新增可选 `validation` 字段；Simulator 产生的回执包含 apply_action **实际复验**的完整结果，供执行后审计使用，而不是用第一次候选验证替代实际执行证据。
- Simulator 的公开状态/配置/命令操作用实例级 RLock 串行化。`get_receipt(plan_id)` 查询当前进程内回执；`cancel_pending_action()` 取消未执行命令并返回 cancelled，无 pending 时返回 null。配置修改后仍须重新规划，可用取消接口解除旧 pending。锁不提供多进程、分布式或真实设备并发保证；control_step 的多步调用不是整个云端事务。
- JSONL 新增 `execution_audit`（实际执行状态与实际复验结果的对照）和 `operational_error`。summary/CSV 新增 failure_kind、执行越界率、实际观测时间与能量统计。执行越界数按“有任一越界的已执行区间数”计数，不按每条错误重复计数；分母为 completed_intervals，无执行时越界率为 null。
- 审计覆盖 SOC/能量变化、储能功率、PCC 进出口、母线电压、线路负载、功率平衡、PV、普通/关键负荷及方案/状态/配置绑定。缺少实际复验证据不会当作安全。
- 不完整 episode 的完整周期保障率/新能源利用率仍为 null；新增能量字段只记录已实际推进的区间，不外推失败后的供电。local_control_latency_ms 仍只是本地函数耗时，不是云端事件到执行耗时。
- batch 保留合理的无解/约束拒绝样本（退出码 0），但缺依赖、求解器故障、执行异常或执行审计失败时退出码 2，并保留日志与汇总。不会把“程序故障”统计成正常的不可行样本。
