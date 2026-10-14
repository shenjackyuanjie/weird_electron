# 三类事故与可重复运行

[文档首页](README.md) · [模型](model.md) · [API](api.md)

## 场景接口

```python
from simulator.simulator import MicrogridSimulator

sim = MicrogridSimulator()
sim.trigger_scenario("A")
state = sim.get_state()
assert state.scenario_id == "A"
assert state.pv_available_kw == 100
```

场景只改变外部条件和约束，不执行恢复调度。随后应调用 `control_step`，或手动完成优化→校验→提交→step。

| ID | 默认改变 | `severity` 含义 |
|---|---|---|
| `A` 光伏骤降 | PV 可用功率降至不超过 100 kW | **事故后 PV 可用功率，kW** |
| `B` 弱网交换受限 | PCC 进口上限降至不超过 40 kW，保持并网 | **事故后进口上限，kW** |
| `C` 储能降额/告警 | 放电上限降至不超过 20 kW，告警 `ESS_DERATED` | **事故后放电上限，kW** |
| `normal` | 恢复三项默认场景参数，清空告警 | 不需要传入 |

`severity` 不是百分比、下降幅度或无量纲风险等级。有效值为有限非负数；0 合法。实际结果取 `min(config 原值, severity 或默认值)`，所以场景不会把原本只有 60 kW 的 PV 提高到 100 kW。

```python
sim.trigger_scenario("C", severity=10)  # 放电能力最多 10 kW
assert sim.get_state().battery_discharge_max_kw == 10
sim.trigger_scenario("normal")
```

每次触发先恢复 PV 可用功率、PCC 进口限制、储能放电限制到 config，再施加一个事故。因此先 A 后 B 是**切换场景**，不是叠加两个事故。复合事故尚无公共场景实现；原计划中的组合 Demo 需要另行设计并经集成确认。

## 触发、恢复与 reset 不同

触发场景会增加 `state_revision`，取消 pending 命令，保留模拟时间和 SOC，将 `pcc_voltage_pu` / `grid_power_kw` 清为 null。已有 PV 实际设定值会被限制到新的可用范围，但这个状态并不是新的已验证运行点。

`trigger_scenario("normal")` 恢复外部参数，不恢复初始 SOC，也不把已经削减的负荷立刻变成已供上电。下一次安全执行才产生新的电气结果。

`reset()` 才会恢复全部初始状态和模拟时间，生成新 run_id，并清空回执。需要留存回执和日志时先导出，不能依赖 reset 后继续查询旧记录。

## Demo 的时序

`run_episode` 至少 3 个区间：第 0 个正常；第 1 个开始前注入事故；最后一个开始前切换正常参数。默认六步对应“正常 1 步、事故 4 步、正常参数恢复 1 步”。

恢复参数由测试运行器预设触发，不是优化器决定事故结束。应分别展示“事故期间找到安全调度”和“外部条件恢复后重新调度”，不能把预定恢复时间当成算法恢复速度。

## 批量场景

`run_batch` 对每个 `seed=0..cases-1` 创建独立的 `random.Random(seed)`，两策略复用同一个 config 和事故值。

| 随机参数 | 区间 |
|---|---|
| 初始 PV | 220–400 kW |
| 关键负荷 | 180–230 kW |
| 普通负荷 | 200–330 kW |
| PCC 进口上限 | 50–160 kW |
| 初始 SOC | 0.10001–0.85 |
| 储能铭牌放电上限 | 80–220 kW |
| A 的事故后 PV | 10–100 kW |
| B/C 的事故后上限 | 5–40 kW |

场景依 seed % 3 在 A/B/C 间轮换。批量 CSV/summary 保存 `seed` 和 `severity_kw`；config.json 只保存初始配置，复现事故还需要对应 severity。

seed 不固定 UUID、真实代码耗时或所有跨版本浮点末位。对比时固定代码提交、依赖环境、配置和事故值，再比较约束及数值容差内的结果，不要求 JSON 字节完全一致。

## 从一个失败目录复现

以批量输出的某个子目录为输入，可在 Python 中读取 config 和 summary，调用：

```python
import json
from pathlib import Path
from power_engine.contracts import MicrogridConfig
from simulator.cli import run_episode

case = Path("outputs/batch/seed-006-optimizer")
cfg = MicrogridConfig.model_validate_json((case / "config.json").read_text(encoding="utf-8"))
old = json.loads((case / "summary.json").read_text(encoding="utf-8"))
summary, trace = run_episode(cfg, old["scenario_id"], policy=old["policy"],
                             steps=old["requested_intervals"], severity=old["severity_kw"])
print(summary)
```

合理无解必须保留；不要调宽 Validator 只为让随机实验全绿。缺少依赖、求解器报错、证据审计失败则属于需要修复的运行问题，见[实验指标](experiments.md)。
