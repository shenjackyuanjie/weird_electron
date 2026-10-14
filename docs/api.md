# Python API 与可运行示例

[文档首页](README.md) · [数据协议](contracts.md) · [场景](scenarios.md)

## 推荐入口：完整本地闭环

```python
from simulator.controller import control_step
from simulator.simulator import MicrogridSimulator

sim = MicrogridSimulator()
sim.trigger_scenario("A")
result = control_step(sim)
if not result["success"]:
    raise RuntimeError(result)
assert result["receipt"]["status"] == "applied"
print(result["state"]["battery_soc"])
```

`control_step(simulator, policy="optimizer", max_replans=1)` 支持 optimizer/baseline；重规划参数仅接受整数 0/1/2，默认对应阶段二的一次重规划。它读取一份 state 快照，对候选校验，通过后调用 Simulator 的独立执行入口。返回字典包含 success、before、state、attempts、operational_error；成功增加 receipt，失败增加 error_code，必要时附 message 或 optimization。

一条 attempts 包括 plan、validation、optimization_status、objective；不能假定每次失败都有 attempts（无解或计算错误可能没有候选）。

`control_step` 本身不计算 execution_audit；`run_episode` 在每次成功控制后调用审计。单独调用时按下面示例自行审计。

## JSON 手工链路

仓库提供[完整手工示例](../examples/manual_dispatch.py)，执行：

```bash
python -m examples.manual_dispatch
```

示例真实调用 `invoke("optimize_dispatch")` → `invoke("validate_plan")`，最多反馈一次；只有通过才调用 apply_action/step，并检查执行审计。它同时演示 request_id 贯穿、相同命令的幂等接收和回执查询。不会拿到 plan 就直接执行，也不会伪造 validation。

下面是适配器的最小错误例子，完全不需要潮流：

```python
from power_engine.api import invoke

bad = invoke("optimize_dispatch", None)
assert bad["ok"] is False
assert bad["error_code"] == "INVALID_INPUT"
```

具体参数形状见[协议](contracts.md)。`config` 是第三个本地参数，不允许塞入远端 payload。JSON 文本解码由调用方负责。

## 确定性函数

| 函数 | 输入 | 返回 / 注意 |
|---|---|---|
| `run_power_flow(state, plan, config=None)` | 模型或对应字典 | PowerFlowResult；试算无副作用，不代替 Validator |
| `optimize_dispatch(state, config=None, *, duration_seconds=None, feedback=None)` | 状态、可信配置、可选同状态反馈 | OptimizationResult；可能无 plan |
| `fixed_rule_dispatch(state, config=None, *, duration_seconds=None, feedback=None)` | 同上 | 固定顺序候选，不运行优化器 |
| `validate_plan(state, plan, config=None)` | 当前状态和候选 | ValidationResult；读取 `.passed` 或 wire 的 `pass` |
| `audit_execution(before, after, plan, receipt, config)` | 一次执行的完整证据 | `{passed, violated_rules}`；规则 code 列表 |

导入分别来自 `power_engine.power_flow/optimizer/baseline/validator` 和 `simulator.metrics`。这些函数不执行设备命令。输入校验错误可抛 ValueError/Pydantic ValidationError；不要只捕获 EngineError。

`run_power_flow` 可以试算一个不安全但结构合法的计划，甚至计划的状态指纹不匹配。**潮流收敛不能作为放行依据**；必须使用 validate_plan，且执行入口仍需复验。

## Simulator 方法

| 方法 | 返回 | 副作用 |
|---|---|---|
| `MicrogridSimulator(config=None)` | 新实例 | 初始化一次 reset |
| `get_state()` | MicrogridState | 无 |
| `reset()` | 初始 MicrogridState | 重置时间/SOC、生成新 run_id、清空 pending/receipts |
| `trigger_scenario(id, severity=None)` | 新 MicrogridState | 修改事故条件、revision+1、取消 pending；不推进时间 |
| `apply_action(plan)` | accepted 或已有回执 | 当前状态重新校验后暂存命令；不推进时间 |
| `step(dt_seconds=None)` | `(MicrogridState, ExecutionReceipt)` | 匹配已验证时长后推进一个完整区间 |
| `get_receipt(plan_id)` | ExecutionReceipt 或 None | 查询本实例内存记录 |
| `cancel_pending_action()` | cancelled 回执或 None | 取消 pending；不改变物理状态/时间 |

`sim.config` 可替换可信配置，但不会把 state 的所有设备值自动重置。已接收计划会因配置指纹改变而在 step 被拒。部署中不要把热改 config 当成场景接口；初始化新实例或明确 reset/重新规划。

每个 plan 只对应一次区间。无 pending 的 step 抛 NO_PENDING_ACTION，不能用无限 `while True: sim.step()` 构造一个假运行的设备。需要每周期完整控制，并处理调度失败。

## 实验函数

`run_episode(config, scenario_id, *, policy="optimizer", steps=6, severity=None)` 返回 `(summary, trace)`，不会自动写文件。`write_episode(path, config, summary, trace)` 写三类文件。`run_batch(output: Path, cases=40, steps=4)` 写配对目录/CSV并返回批量汇总。

```python
from pathlib import Path
from power_engine.contracts import MicrogridConfig
from simulator.cli import run_episode, write_episode

cfg = MicrogridConfig()
summary, trace = run_episode(cfg, "B", severity=25, steps=6)
write_episode(Path("outputs/custom-B"), cfg, summary, trace)
print(summary["complete"], summary["failure_kind"])
```

保存定制实验时也自行记录 severity；`write_episode` 原样保存 summary，不自动推断额外参数。CLI 的 batch 会主动把 severity_kw/seed 加进 summary。

## 完整运行示例与测试

[本地三阶段示例](../examples/local_loop.py) 可以通过 `python -m examples.local_loop` 执行；[手工 JSON 示例](../examples/manual_dispatch.py) 展示不依赖 control_step 的调用方逻辑。两者都由 `tests/test_documentation.py` 的真实 AC 集成测试执行。

示例只使用本地 B 线能力；它们不是 MCP 服务、IoTDA SDK 示例或云端执行授权方案。A/C 封装时的职责见[交接](handoff.md)。
