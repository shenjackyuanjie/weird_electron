# A/B/C 集成交接与阶段验收

[文档首页](README.md) · [数据协议](contracts.md) · [API](api.md) · [运行](getting-started.md)

## 已交付的 B 线能力

Simulator、SOC、A/B/C场景、run_power_flow、optimize_dispatch、validate_plan、固定规则baseline、本地控制闭环、JSON适配器、执行回执与审计、配对实验、测试和文档已具备本地入口。

MCP Server、IoTDA遥测/命令、FunctionGraph、GeminiDB、AgentArts、统一HTTP后端和Dashboard **尚未实现**。仓库对应目录是预留，不是可启动的服务。B提供内部函数，不把pandapowerNet暴露给其他线。

原计划§8.2把算法归B，§8.1另有“调用A提供的确定性工具”的文字歧义。按当前实现，算法由B维护；MCP服务封装、部署及认证的主责需队长明确，不默认已经分配完毕。

## 交接边界

| 对接方 | 使用本仓库什么 | 仍需对方/集成负责人完成什么 |
|---|---|---|
| A：AgentArts与MCP | JSON Schema、三类只计算工具、结构化错误/拒绝原因、场景与baseline运行器 | 专业Agent、Coordinator、Workflow、MCP传输、调用超时/权限、Trace、Single/Multi-Agent策略适配 |
| C：云与产品 | Simulator状态出口、可信命令入口、accepted/applied/cancelled回执、模拟时钟和指标语义 | IoTDA产品/命令映射、遥测上传、时序存储、事件检测、HTTP后端、Dashboard、ECS进程管理 |
| 队长/集成 | 协议草案、默认参数、已知限制、可复现测试 | 冻结单位/字段/设备身份、参数与SOP、职责、风险分级、最终指标和发布版本 |

不要让A/C手动从显示数据猜调度功率，也不要在前端接收到accepted时就改图表示设备已执行。

## 建议的只读/计算/执行划分

| 未来能力名 | 当前可复用实现 | 约束 |
|---|---|---|
| get_microgrid_state | `sim.get_state().wire()` | 服务端可信实例提供，不让调用方替换实际状态 |
| run_power_flow | `invoke("run_power_flow", payload, config)` | 只试算；收敛不等于安全 |
| optimize_dispatch | `invoke("optimize_dispatch", payload, config)` | 只提案；无解必须结构化保留 |
| validate_plan | `invoke("validate_plan", payload, config)` | 独立拒绝权；不能把外层ok当作pass |
| execute_action | 后续可信执行服务包装 `sim.apply_action(plan)` 和 `sim.step()` | 目前无远端工具；必须认证、授权、复验最新状态、绑定plan_id |
| 查询/取消 | `get_receipt`、`cancel_pending_action` | 单实例内存作用域；取消后新命令用新ID |

forecast_pv、forecast_load、diagnose_alarm尚无对应预测/诊断实现，不应把预设曲线或告警字段包装成已验证模型。

## 先做本地无云合同测试

A/C先按README运行Demo，再分别读取state、通过JSON工具提出和验证候选、在可信入口提交、推进并查询实际回执。完整可运行链见[manual_dispatch示例](../examples/manual_dispatch.py)。

对接最少验证：结构化非法输入；关键负荷削减被拒；旧state方案被拒；同ID同内容重投不重复执行；同ID不同内容拒绝；事故取消pending；配置变更阻止旧批准执行；失败后保留证据与null指标。不要仅测试一个正常请求。

step使用模拟时间，没有真实五秒定时线程。C接入实时设备模拟时，需要自己调度轮次，并定义采样、过期和失败处理，不能认为构造Simulator会自动开始遥测。

## 遥测与命令映射要冻结的内容

所有功率kW、SOC0–1、时间带时区；设备id与microgrid_id、run_id/state_revision/request_id/plan_id之间的映射由集成定义。B现有state不是完整IoTDA TelemetryEvent；GridEvent和AgentFinding也尚未定义成最终共同协议。

远端可能出现消息重复、乱序、部分设备执行和ACK丢失。当前本地操作是单实例中的整体状态更新，并未模拟ESS执行成功但负荷命令失败等部分执行。必须另定超时、重试、回执幂等、部分失败处置和重启恢复策略。

不能只传入外部ValidationResult.pass=true就执行。当前apply_action会自行复验真实state/config；后续设备服务同样必须掌握可信约束，并且不向普通Agent开放设备写权限。hash只能绑定内容，不是授权凭据。

## ECS 部署前的边界

目前可在ECS像普通Linux机器一样安装并运行本地CLI，用完整测试验证环境；这不代表已经存在HTTP监听端口。仓库没有systemd单元、Dockerfile或可执行MCP服务器，不应编造启动命令。

开发验证建议先保留一个可信Simulator实例、单进程执行所有写操作。实例锁不保护多worker或多容器共享的设备；扩容前设计持久化/跨进程串行与命令账本。receipt只在内存中，reset或进程重启会丢失。

部署方还需服务账号与最小权限、配置来源、凭据管理、HTTPS、日志轮转、资源限制、告警和备份。密钥不入库；不是给本地适配器加一个公开URL就完成生产部署。

## 尚待确认的模型与产品工作

默认设备容量、效率、功率、电压限值、馈线和目标权重均是演示假设。批量随机配置用于软件验证，不是实际校园/工业微电网的建模结果。

B场景当前为限PCC仍并网，完全断网/孤岛、构网型储能、频率动态、真实保护和复合事故仍缺模型。原计划恢复时延与MCP/Agent指标需要云端真实时间戳与调用链；本地perf_counter不能替代。

最终阶段需把Single-Agent/Multi-Agent接入同一场景、配置和执行门，对比相同seed，保留失败案例与真实Trace。固定规则和LP对照已有结果，不能把它们改名当三套Agent实验。

## 接入验收清单

先冻结共同Schema与参数，再以本地示例跑通读状态→提案→验证→执行→新状态。其次接设备上报和真实命令回执，证明accepted与applied不同。然后接MCP权限与Agent工作流，证明拒绝方案不能执行、有限重规划后仍失败会停止并交人工。最后接Dashboard与云端指标，显示真实来源、空值及失败，不用动画补齐链路。

本清单是后续工程建议与交接要求，不声称这些云端阶段已完成。
