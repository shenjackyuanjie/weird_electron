# B 线数据协议 v0.1

[文档首页](README.md) · [API 示例](api.md) · [执行语义](architecture.md)

本文件解释当前 `power_engine/contracts.py`，是 B 线接口草案，不代表 A/C 和集成负责人已经冻结全部云端协议。模型变更先修改本文件、再改 Schema/调用方/测试。

## 单位、类型、时间和信任边界

功率 kW，电池容量 kWh，时长秒，SOC 0–1，电压 p.u.，频率 Hz。储能功率正值为放电，负值为充电；PCC 功率正值为进口，负值为出口。不要在 JSON 中混入 MW 或百分数 SOC。

所有 WireModel 默认拒绝未知字段和 NaN/Infinity，实例 frozen。其余普通字段仍采用 Pydantic 默认类型转换，**并非整个模型 strict-mode**。

`Duration` 严格接收数值，范围 `(0,300]`，拒绝布尔值、字符串、数组、非有限数。`Identifier` 用于 request_id/plan_id：严格字符串，1–128 字符，至少包含一个非空白字符；不会自动去除首尾空白。不要依赖字符串化任意对象。

`timestamp` 必须带时区，是模拟时钟，不是事件接收的墙钟时间。state 默认模拟起点固定；run_id 是 reset 隔离标识；revision 是状态变化序号。

`.wire()` 输出可 JSON 序列化的字典，启用 alias。`checked` 在公共输入边界重新验证已有模型，避免 `model_copy(update=...)` 绕过类型约束。`fingerprint` 对 wire 字典按键排序、紧凑 JSON 编码后计算 SHA-256；不是签名或权限凭证。

当前和预测 SOC 的运行范围共用 1e-10 容差；原始 SOC 不裁剪、不四舍五入。Schema 的绝对 [0,1] 范围仍然生效。

## 导出的七类顶层 Schema

```bash
python -m simulator schemas --output outputs/schemas
```

导出 `MicrogridConfig`、`MicrogridState`、`DispatchPlan`、`PowerFlowResult`、`OptimizationResult`、`ValidationResult`、`ExecutionReceipt`。`BatteryConfig`、`NetworkConfig`、`RuleViolation` 是嵌套定义。字段约束以本提交生成的 Schema 为准，不能混用旧 CI 的导出。

### MicrogridConfig

可信部署配置，包含 battery、network、步长、初始出力/负荷、PCC 上限、额定频率和目标权重。完整字段和默认值见[模型表格](model.md)。它不是 `invoke` 的远端 payload 字段；配置由服务端调用参数传入。

### MicrogridState

| 字段或字段组 | 语义 |
|---|---|
| `schema_version` | 固定 `"0.1"` |
| `microgrid_id`、`run_id` | 微电网标识、一次 reset 周期标识 |
| `state_revision`、`timestamp` | 非负序号、带时区模拟时间 |
| `scenario_id` | `normal/A/B/C` |
| `pv_available_kw`、`pv_power_kw` | 可用/实际 PV，非负；实际不超过可用 |
| `load_critical_kw`、`load_normal_kw` | 两类负荷需求，非负 |
| `critical_served_kw`、`normal_served_kw` | 实际供电功率，非负且不超过需求 |
| `normal_shed_max_kw` | 普通负荷允许削减上限，不超过普通需求 |
| `battery_soc`、`battery_power_kw` | SOC 与储能当前有功 |
| `battery_charge_max_kw`、`battery_discharge_max_kw` | 当前设备能力；还需与 config 铭牌及能量边界取交集 |
| `grid_import_max_kw`、`grid_export_max_kw` | 当前 PCC 双向能力 |
| `grid_available`、`grid_voltage_pu` | 主网是否可用、上级给定电压 |
| `frequency_hz` | 额定/场景输入，不是动态仿真结果 |
| `alarm_code` | null 或告警，例如 `ESS_DERATED` |
| `pcc_voltage_pu`、`grid_power_kw` | AC 结果；初始/刚触发事故时 null |

初始的负荷供电字段是初值，不是已经通过潮流证明的运行证据。展示安全状态时应核验实际 `applied` 回执及其 validation，而不是仅查看 served 字段。

### DispatchPlan

| 字段 | 要求与含义 |
|---|---|
| `schema_version` | `"0.1"` |
| `request_id`、`plan_id` | Identifier；省略则自动生成 UUID 字符串 |
| `state_fingerprint` | 64 字符，必须匹配完整当前状态的 fingerprint |
| `duration_seconds` | 默认 5；Duration；执行必须使用相同时长 |
| `pv_power_kw` | PV 实际设定值，非负 |
| `battery_power_kw` | 正放电、负充电 |
| `normal_shed_kw` | 非负，默认 0；Validator 检查可削范围 |
| `critical_shed_kw` | 非负，默认 0；Schema 可表达坏方案，但 Validator 拒绝一切非零值 |
| `expected_grid_kw` | 可选 LP 估计；不是可下发的主网功率命令，Validator 不依赖它 |

修改 plan 任意内容后必须重新验证；重规划产生新 plan_id。不要复用旧批准或篡改指纹来绕过过期检查。

### PowerFlowResult / OptimizationResult

`PowerFlowResult` 有 converged、error_code、message，以及 PCC/极值电压、线路负载、PCC 功率、损耗和功率平衡残差。converged=true 要求全部电气字段存在且有限、没有 error_code，PCC 电压处于报告的极值范围内。converged=false 不代表“零电压正常”，应读取错误。

`OptimizationResult.status` 为 `optimal/feasible/infeasible/error`。优化器的 optimal 只指 LP，固定规则的 feasible 也只是候选。`plan` 可以为 null；必须先检查，才能进入 Validator。`objective` 是优化器单区间目标值，固定规则没有同口径 objective。

### ValidationResult

Python 属性叫 `passed`，wire/JSON 键为 **`pass`**。有 request_id、plan_id、state_fingerprint、plan_fingerprint、config_fingerprint、predicted_soc、power_flow 和 violated_rules。

每条 RuleViolation 是 `{code, message, actual, limit}`；actual/limit 允许 null。硬规则失败时 power_flow 为 null，不浪费潮流计算；拒绝反馈不得跨状态或配置复用。

### ExecutionReceipt

字段：request_id、plan_id、status、timestamp、state_revision、plan_fingerprint、validation。

status 仅为 accepted/applied/cancelled。validation 保存 **apply_action 在最新状态执行的复验**，不是调用方提交的批准；applied 沿用该证据。兼容 Schema 允许 validation=null，但执行后审计会拒绝缺证据的回执。

`apply_action` 只接收；`step` 才执行。状态/配置指纹改变、时长不符时拒绝执行。取消不推进时间；相同 ID/内容再次提交返回当前回执，不能把 cancelled 变成一条新的命令。reset 清空本实例回执。

## JSON 适配器协议

入口 `invoke(tool, payload, config=None)` 接收**已解码的对象**，不是 JSON 文本。null、数组等顶层值返回 INVALID_INPUT，并生成兜底 request_id。未知工具返回 UNKNOWN_TOOL。

| tool | 允许的 payload 字段 |
|---|---|
| `optimize_dispatch` | 必需 state；可选 request_id、duration_seconds、feedback |
| `run_power_flow` | 必需 state、plan；可选 request_id |
| `validate_plan` | 必需 state、plan；可选 request_id |

规划 payload 的 duration_seconds 省略或 null 使用配置步长；plan 自身的 duration_seconds 不能为 null。feedback 是之前的 ValidationResult，必须匹配同一个状态和配置。

成功工具调用返回 `{ok:true, request_id, result}`；输入或已定义工具错误返回 `{ok:false, request_id, error_code, message}`。**外层 ok=true 不表示优化有解、潮流收敛、校验通过或命令已执行**，必须逐层检查。

优化调用把外层 request_id 写入生成的 plan。验证/潮流未传 request_id 时继承 plan.request_id；显式传入不同 ID 则拒绝。存在有效 request_id 时错误也保留它；无法验证 ID 时返回生成的兜底 ID。

没有 `invoke("fixed_rule_dispatch", ...)` 或 `invoke("execute_action", ...)`。固定规则和 Simulator 通过 Python 调用；远端执行应由后续独立服务封装。意外程序缺陷仍可能抛异常，上层应记录追踪与告警，不能伪造安全结果。

## 错误与规则分层

| 层 | 主要 code |
|---|---|
| 输入/适配器 | INVALID_INPUT、UNKNOWN_TOOL |
| 当前状态/硬规则 | STALE_STATE、CURRENT_SOC_LIMIT、CRITICAL_LOAD_SHED、NORMAL_SHED_LIMIT、PV_AVAILABILITY、ESS_DISCHARGE_LIMIT、ESS_CHARGE_LIMIT、SOC_MIN、SOC_MAX |
| AC | GRID_IMPORT_LIMIT、GRID_EXPORT_LIMIT、VOLTAGE_LOW、VOLTAGE_HIGH、LINE_OVERLOAD、POWER_BALANCE、POWER_FLOW_FAILED、INVALID_POWER_FLOW_RESULT、DEPENDENCY_UNAVAILABLE、INVALID_LOAD、UNSUPPORTED_ISLAND_MODE |
| 规划 | NO_FEASIBLE_DISPATCH、OPTIMIZER_FAILED、STALE_FEEDBACK |
| 接收/执行 | UNSAFE_PLAN、ACTION_PENDING、NO_PENDING_ACTION、DURATION_MISMATCH、STALE_CONFIG、IDEMPOTENCY_CONFLICT |
| 控制/实验 | VALIDATION_REJECTED、INVALID_ENGINE_RESULT、EXECUTION_FAILED、EXECUTION_AUDIT_FAILED |

执行后审计返回 `{passed, violated_rules}`，其中 violated_rules 是**字符串 code 列表**，不是 ValidationResult 中的对象列表。它还有 RECEIPT_BINDING、MISSING_EXECUTION_VALIDATION、EXECUTED_SOC_ENERGY 等证据审计规则。不要把两种形状混用；完整实现见 `simulator/metrics.py`，处理方式见[排错](troubleshooting.md)。

## 尚未由 B 线冻结的对象

原计划要求的 TelemetryEvent 设备封包、GridEvent、AgentFinding、IoTDA 回执映射和远端执行授权仍需 A/C 与集成负责人共同定义。本次导出七类本地 Schema 不等于已经完成全部云端协议。
