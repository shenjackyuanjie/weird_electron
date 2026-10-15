# GridHive 首次 ABC 联合测试：B 线接口交付

[文档首页](README.md) · [现有协议](contracts.md) · [现有 API](api.md) · [样例生成器](../examples/joint_pv_drop.py)

基线：`494508a0335cdcabf5496c28cdf3db26d5c52db8`，2026-10-15 整理。本文沿用队内本轮通知中的 GridHive 名称；仓库包名和原计划仍为 GridGuardian，不做全项目改名。

## 1. 本轮范围与已知进展

队内通知称 A 已在 AgentArts 调用 B 的优化和 AC Validator，跑通 Workflow → MCP → Python 解析 → 返回。本文将其作为团队提供的进展，不冒充 B 在本轮独立复测了该云端链路。本仓库的 MCP 目录仍是预留目录，不代表 A 线独立部署不存在。

本轮只整理当前计算接口、可运行 JSON 样例、C 遥测映射草案及最小改动清单。先冻结字段，再本地 B+C，再接 A。只做光伏骤降，设备命令仅限 C 的虚拟储能；不新增前端、数据库或云服务，不修改优化器/Validator/SOC 的生产实现，也不提前假定 C 的真实路径和 JSON 形状。

## 2. B 线当前真实入口

| 能力 | Python 入口 | JSON payload 必填 | 可选 |
|---|---|---|---|
| 优化 | `power_engine.api.invoke("optimize_dispatch", payload, config)` | `state` | `request_id`、`duration_seconds`、`feedback` |
| 安全校验 | `power_engine.api.invoke("validate_plan", payload, config)` | `state`、`plan` | `request_id` |
| 潮流试算 | `power_engine.api.invoke("run_power_flow", payload, config)` | `state`、`plan` | `request_id` |

`invoke` 接收已解码的字典，不接收 JSON 字符串。原生函数入口仍为 `optimize_dispatch(state, config, ...)`、`validate_plan(state, plan, config)`、`run_power_flow(state, plan, config)`；返回 Pydantic 对象，用 `.wire()` 输出 JSON 字典。上表是 B 内部适配器，不是 HTTP 路由或完整 MCP JSON-RPC 请求。A 需确认现有 MCP 的工具名/arguments 外壳如何转成这些 payload。

`config` 是第三个 Python 参数，由服务端加载。不得塞进 payload，也不能让 Agent 临时覆盖。三个工具必须使用同一份已冻结配置。省略时会使用演示默认配置；联调应显式加载 `config.json`，并记录 `fingerprint(config)`。

**关键格式：**SOC 为 0–1，功率 kW，容量 kWh，时间秒，带时区时间戳。储能正值放电、负值充电；PCC 正值购电、负值送电。时长传数值 `5`，不传 `"5"`/布尔值；范围 `(0,300]`。request_id/plan_id 为 1–128 字符非空白字符串。

### 返回值必须分层判断

成功调用的外壳是 `{ok:true, request_id, result}`。输入错误是 `{ok:false, request_id, error_code, message}`。

| 检查对象 | 需要检查什么 |
|---|---|
| 优化结果 | `ok`，再检查 `result.status` 为 optimal/feasible 且 `result.plan` 非 null；不代表安全 |
| Validator | `ok`，再检查 `result.pass`；wire 键是 pass，Python 属性才是 passed |
| AC 结果 | `result.power_flow.converged`；收敛不等于电压/PCC 等约束通过 |
| REJECT | `result.pass=false`，原因在 `result.violated_rules[]`，每条有 code/message/actual/limit |
| PASS | `result.pass=true`，规则列表为空，且保留同状态/方案/配置指纹和 AC 结果 |

`ok=true` 的 REJECT 是正常工具返回，不是通信失败。缺少 state 或非法 SOC 是 INVALID_INPUT，不应伪装成一例成功完成的安全校验。硬规则拒绝时 `power_flow=null`；这是没有运行 AC，不是 AC 通过。

## 3. state 必填项、缺省项与快照规则

Schema 无默认值、调用时必须提供的 12 项：

```text
pv_available_kw, pv_power_kw,
load_critical_kw, load_normal_kw,
critical_served_kw, normal_served_kw, normal_shed_max_kw,
battery_soc, battery_charge_max_kw, battery_discharge_max_kw,
grid_import_max_kw
```

但集成时不要只传最小字段。**完整传递全部规范化 state 字段**，尤其是 `run_id`、`state_revision`、`timestamp`、`battery_power_kw`、`grid_available`、`grid_voltage_pu`、`grid_export_max_kw` 和 `frequency_hz`。它们有默认值不等于可以代替真实遥测；run_id 省略会自动生成，分两次解码可能使同样的输入在优化/校验时变成不同状态。

`DispatchPlan` 无默认值的字段是 `state_fingerprint`、`pv_power_kw`、`battery_power_kw`。联调不要自行拼装最小 plan，应完整转交优化器返回的 `result.plan`。request_id、plan_id、duration_seconds、normal_shed_kw 等已经包含在返回对象中。

一个决策周期的规则：

1. 只读取一次 C 遥测，结合 PV/负荷/PCC 上下文，规范化为完整 state 并保存。
2. 用这一份 state 调优化器；将返回的 plan 原样交给 Validator，仍使用这份 state 和 config。
3. 首次拒绝时可将 **Validator 的 result 对象**作为 feedback 原样返回优化器；不传整个 `{ok,...}` 外壳，不换 state/config。request_id 沿用同一决策周期，重规划使用新 plan_id。
4. 新遥测到达后建立新 revision；旧计划不再代表最新设备状态。执行前由桥接层确认在线/新鲜度/版本，并复验实际执行上下文；状态变化就重新规划，不能改指纹假装没变。

优化器生成的 plan 绑定完整规范化 state，Validator 检查该指纹；run_power_flow 仅做试算，不能代替过期检查或 Gate。即使只改变时间戳、revision 或不参与目标函数的观测字段，也可能触发 STALE_STATE。不要删字段、四舍五入、重新创建 run_id，或把计划中的 `expected_grid_kw` 当成主网指令。`config_fingerprint` 在 ValidationResult 中，plan 本身没有 config_fingerprint；部署桥接层仍须固定配置版本。

## 4. C → B：待双方确认的映射

下面是**拟议的 C 归一化响应**，不是已获得的 IoTDA 原始报文，也不是现有 B Schema。`examples.joint_pv_drop` 导出对应的 `c-telemetry.proposed.json`。真实字段名、HTTP/MQTT/函数调用方式和鉴权仍由 C 给出。

```json
{
  "device_id": "ess-virtual-demo",
  "boot_id": "fixture-boot-001",
  "sequence": 1,
  "measured_at": "2026-10-15T00:00:00+09:00",
  "online": true,
  "soc": 0.6,
  "soc_unit": "ratio",
  "power_kw": 0.0,
  "positive_power": "discharge",
  "power_unit": "kW",
  "charge_max_kw": 150.0,
  "discharge_max_kw": 200.0,
  "profile_id": "joint-ess-proposed-v1"
}
```

| C 的拟议字段 | B 目标 | 处理要求 |
|---|---|---|
| soc | battery_soc | 0–1 原样；若 C 明确用百分数，则除以 100；禁止凭大小猜单位 |
| power_kw | battery_power_kw | 是实际当前功率，不是待执行指令；若 C 正充电，显式取反 |
| charge_max_kw / discharge_max_kw | battery_charge_max_kw / battery_discharge_max_kw | 当前可用能力；不得用缺省铭牌代替丢失约束；最终还与 config 限值、SOC 能量边界取交集 |
| measured_at | timestamp / 遥测侧记录 | 保留带时区的测量时间；接收时间另存；明确模拟时间与墙钟时间，禁止混算数据年龄 |
| device_id / boot_id / sequence | 桥接层快照元数据 | 校验设备绑定、重启和乱序；由桥接层统一分配 run_id/revision，不能每次读状态都 reset |
| online | 桥接层前置检查 | **绝不能映射到 grid_available**；后者指主网可用性，当前 state 没有 ESS 在线字段 |
| profile_id | 可信 config 的版本映射 | 对齐容量、效率、SOC 范围、铭牌功率；不能随遥测任意抬高安全上限 |

SOC 容量、充放电效率、soc_min/soc_max 在 `config.battery`，不在 state。C 若也有这些参数，双方须冻结一致配置。动态约束只允许保守收紧；额外温度/告警等当前没有自动派生限值的模型，必须先约定安全状态或降额映射，不能仅写个 alarm_code 就认为已经保护。

储能遥测**不足以单独构造全网 state**。首轮 PV 可用/实际功率、关键/普通负荷、可削负荷、PCC 上限和电网电压由 B 的明确测试上下文提供；不是偷偷使用未知默认值，更不能把这些称为 C 的实测。缺失必需遥测、设备离线、过期、乱序/重复、配置不一致时，建议桥接层拒绝本轮发送并记录结构化原因。过期阈值、时钟模式、最大允许决策延迟需共同冻结；现有计算函数只有类型/指纹检查，没有这些 C 设备检查。

## 5. 第一轮为什么另设“仅需 ESS 动作”的测试配置

仓库默认是关键负荷 200 + 普通负荷 300 = 500 kW。PV 降至 100、主网最多 100、储能最多 200 时，即使先忽略损耗仍需至少削 100 kW 负荷。其 PASS plan 是一组动作，不能只执行电池字段，漏掉 normal_shed_kw 后仍宣称安全闭环。

**待冻结的首轮配置**改为关键负荷 200、普通负荷 150，总需求 350 kW；保留 PV 350→100、PCC 上限 100、储能最大放电 200/充电 150、容量 500 kWh、SOC 0.6、效率 0.95、每区间 5 秒。state 中明确 `normal_shed_max_kw=0`。这不是修改全项目默认值，配置只用于联合测试样例。

事故后初始 LP 候选应为 PV 100、储能放电 150、主网估计 100、削负荷 0。真实 AC 计入线路损耗后，实际进口超限，应 REJECT；带损耗反馈重规划后增加储能放电，期望通过 AC。生成器会实际调用当前算法检查这些条件，不满足即报错，不会输出伪造的 PASS。

即使采用此配置，后续从 C 的 SOC/能力构建状态时仍可能无解，不能固定下发样例里的功率。若任何运行生成了削负荷或弃光等当前执行链不支持的动作，应整体拒绝/换测试上下文，不截掉字段继续下发。

## 6. 请求和返回 JSON 的生成、重放

在仓库根目录、安装好当前依赖后运行：

```bash
python -m examples.joint_pv_drop --output outputs/joint-pv-drop
python -m pytest --require-ac tests/test_joint_pv_drop.py
```

输出完整 `config.json`、`state.json`、`bundle.json`、`c-telemetry.proposed.json`，以及下表中的逐个请求/返回文件。CI 测试同样生成这些文件，放进现有 outputs artifact。生成器不接 C、不发任何设备命令。

| 前缀 | 请求 / 返回 | 目的 |
|---|---|---|
| reject-ac.optimize | `.request.json` / `.response.json` | 第一轮优化 |
| reject-ac.validate | `.request.json` / `.response.json` | AC 收敛但 GRID_IMPORT_LIMIT 拒绝 |
| pass.optimize | `.request.json` / `.response.json` | 同状态、同 config、带 feedback 重规划 |
| pass.validate | `.request.json` / `.response.json` | AC 校验通过 |
| reject-hard.validate | `.request.json` / `.response.json` | 故意请求 201 kW 放电，ESS_DISCHARGE_LIMIT，AC 不运行 |

每个请求文件都是可直接传给 invoke 的 payload，不含伪造的 HTTP 路由；返回文件由真实调用取得，保留完整 ID、指纹、预测 SOC、电压、损耗、PCC 功率及拒绝原因。bundle 的 metadata 记录环境和代码基线。该基线是未改变的运行时来源，完整样例实现的提交与 CI run 应一并记录。

以下示例重放 PASS 请求，不执行设备：

```python
import json
from pathlib import Path
from power_engine.api import invoke
from power_engine.contracts import MicrogridConfig

root = Path("outputs/joint-pv-drop")
config = MicrogridConfig.model_validate(json.loads((root / "config.json").read_text(encoding="utf-8")))
payload = json.loads((root / "pass.validate.request.json").read_text(encoding="utf-8"))
response = invoke("validate_plan", payload, config)
assert response["ok"] and response["result"]["pass"]
print(json.dumps(response, ensure_ascii=False, indent=2))
```

快照的时间戳是固定测试时间，不代表在线实时数据。不同次生成的 plan_id 会不同，浮点值应按明确容差比较；不要把这些历史 JSON 直接用作当前设备执行授权。真正 C 遥测进入后，必须重新生成与验证计划。

## 7. B+C 闭环执行时的关键约定（尚待实现/对齐）

**SOC 只能由一个模型推进。** 首轮建议 C 虚拟储能作为 SOC/当前功率的唯一状态来源，B 用 `project_soc` 做预测/复核；B 不再调用自己 Simulator.step 对同一设备重复积分。B 的 apply_action/step/receipt 是本地 Simulator 语义，不是 C 已实现的 IoTDA 命令接口。C 回来的新状态须与预测作对照，不能用 B 预测值覆盖 C 的实际返回。

**指令是有时长的功率设定，不是无限续期。** 以下只是“通过 Gate 后给 C 的归一化命令”建议字段，不是现有 invoke 支持的工具或已冻结 IoTDA command_name：

```text
command_id = plan.plan_id
request_id = plan.request_id
device_id = 已绑定的虚拟 ESS
power_kw = plan.battery_power_kw（按双方确认的符号转换）
duration_seconds = plan.duration_seconds
state_fingerprint / plan_fingerprint / config_fingerprint
```

5 秒从“实际开始应用功率”计时，不从发送 HTTP 或收到 accepted 开始计时。C 要明确是否支持持续时长/到期回零；不支持时先约定受控的单步执行，不可发送一个无期限维持的 150 kW 命令，却使用仅覆盖 5 秒的 SOC 批准。还需对齐功率精度、步进、最小值及延迟；若 C 要求整数功率或量化，必须对量化后的完整 plan 重新校验，不能在 PASS 后悄悄取整。

**ACK 不代表完成。** 必须至少区分命令已接收、开始/完成应用、拒绝/失败/超时。C 的状态名称可以不同，但桥接层不能把 ACK 直接映射为 B 的 applied。约定 command_id 幂等、设备重启后行为和后续遥测关联；同命令重复提交不能重复扣 SOC。收到新状态后核对设备 ID、命令关联、实际功率、测量/执行时间与 SOC，再记录闭环成功。

**在线和快照保护不是验算本身。** 发送入口只允许虚拟设备白名单、同一份已验证的动作及有效快照；状态变化应重读重算，接口失败不得绕过 Gate。指纹不是签名/鉴权。当前 B 没有 C 设备事务、远端状态过期保护或多进程幂等实现，不能把本地实例锁当成这些能力已经存在。

## 8. 对齐后最小改动与第一次验收

| 责任 | 下一步最小工作 | 此前必须得到的输入 |
|---|---|---|
| C | 提供实际状态读取方法及成功/离线/错误 JSON；虚拟指令参数、回执和执行后遥测 | 真实路径或函数、鉴权使用方式、字段单位与时钟来源，不把密钥放进仓库 |
| B | 增加只做数据归一化/快照管理的薄适配层；保持现有计算 API；补缺值/在线/过期/乱序/符号测试 | C 的真实原始样例、设备身份、SOC 档案与动作能力 |
| B+C | 冻结测试 profile；连接 Gate 后的虚拟指令；用 C 新遥测核验实际执行 | 5 秒语义、量化精度、幂等、超时、谁推进时钟/SOC |
| A | 沿用已有 Workflow→MCP 链路，保留 state/plan/result 完整对象；检查 result.pass 后才到执行 | MCP 当前输入/输出样例和实际 Python config 版本；不要再次设计一套不兼容字段 |

本地 B+C 的最小验收记录应包含同一次决策的：C 原始遥测、规范化 state、config 指纹、优化请求/返回、REJECT 原因（可先运行独立坏案例）、PASS 请求/返回、虚拟设备命令与回执、关联到该命令的新遥测，以及 SOC/功率复核。离线、缺 SOC、陈旧状态、重复命令和不支持动作必须不能绕过 Gate。随后将相同请求挂入 A 的现有 MCP/Workflow 复测。

**本轮样例/测试通过只证明 B 的离线契约与真实 AC 案例，不代表本地 B+C 或完整 ABC 联测已经完成。** 当前阻塞是 C 的真实接口和 A 的 MCP 封装字段未在本材料中提供；不据此编造已接入状态。
