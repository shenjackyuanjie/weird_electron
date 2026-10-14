# 电力模型、数学约定与参数

[文档首页](README.md) · [场景](scenarios.md) · [实验](experiments.md)

## 项目要求与实现假设

原计划 §2 要求五类对象、5 秒仿真步、离散 SOC、pandapower 潮流、确定性调度、独立验证和三类事故。本版选择 SciPy/HiGHS，而不是同时依赖 PuLP。

计划没有规定下列设备容量、线路参数、成本权重和电压限值。它们是 `MicrogridConfig` 的演示默认值，需要团队审核，不能当作法规、工程标准或真实设备铭牌。

## 拓扑与潮流

```text
上级参考母线 (ext_grid，给定电压)
             |
      有阻抗馈线 (80 m)
             |
微电网 PCC 母线 — PV / ESS / Critical Load / Normal Load
```

两母线用于避免把全部设备直接接到理想电压源而使电压永远不变。线路不新增能源类型。采用平衡三相 AC 潮流，`runpp(algorithm="nr", numba=False, init="flat", max_iteration=30, tolerance_mva=1e-9)`。每次计算创建独立网络对象，无共享 pandapowerNet，不改变业务状态。

`grid_power_kw` 取**馈线上级端**外网功率，包含馈线损耗；`pcc_voltage_pu` 取**微电网端**母线电压。这两个量的测量位置不同，是有意的约定。电压极值检查包含两个母线。

业务接口功率用 kW，进入 pandapower 除以 1000 变 MW。PV 使用 sgen；储能使用 storage，业务放电正号转换为 storage 的负号。储能、PV 无功为 0；负荷无功为 `P * tan(acos(power_factor))`，削减负荷时有功和无功同比下降。上级网络承担无功平衡。

普通潮流负责计算结果，不自动保证配置的业务 PCC 交换上限。不能靠设置 ext_grid 的 OPF 参数取代独立验证。频率为额定输入，不是本模型计算得到的动态频率。

## 全部默认配置

### 微电网与成本

| 字段 | 默认值 | 单位 / 约束 |
|---|---:|---|
| `step_seconds` | 5 | 秒，严格数值，0 < 值 ≤ 300 |
| `pv_available_kw` | 350 | kW，非负 |
| `load_critical_kw` | 200 | kW，非负 |
| `load_normal_kw` | 300 | kW，非负 |
| `grid_import_max_kw` | 100 | kW，非负 |
| `grid_export_max_kw` | 0 | kW，非负 |
| `grid_voltage_pu` | 1 | p.u.，正数，上级给定电压 |
| `nominal_frequency_hz` | 50 | Hz，正数 |
| `import_cost_per_kwh` | 0.18 | 正的目标权重/能量单位，不假定货币币种 |
| `curtail_cost_per_kwh` | 1 | 弃光惩罚，正数 |
| `shed_cost_per_kwh` | 1000 | 普通负荷削减惩罚，正数 |
| `battery_cost_per_kwh` | 0.22 | 充放电吞吐惩罚，正数 |

### `battery`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `capacity_kwh` | 500 | 容量 > 0 |
| `soc_min` / `soc_max` | 0.1 / 0.9 | 0–1；要求下限 < 上限 |
| `initial_soc` | 0.6 | 必须位于配置的 SOC 上下限之间 |
| `charge_efficiency` / `discharge_efficiency` | 0.95 / 0.95 | 单向效率，0 < 值 ≤ 1 |
| `charge_max_kw` / `discharge_max_kw` | 150 / 200 | 铭牌功率 ≥ 0；实际限制还要与 state 中设备降额取交集 |

### `network`

| 字段 | 默认值 | 单位 / 约束 |
|---|---:|---|
| `nominal_kv` | 0.4 | kV，正数 |
| `length_km` | 0.08 | km，正数 |
| `r_ohm_per_km` | 0.125 | Ω/km，正数 |
| `x_ohm_per_km` | 0.08 | Ω/km，非负 |
| `max_current_ka` | 0.6 | kA，正数 |
| `load_power_factor` | 0.98 | 0 < 值 ≤ 1 |
| `voltage_min_pu` / `voltage_max_pu` | 0.95 / 1.05 | 正数；下限 < 上限 |
| `loading_max_percent` | 100 | %，正数 |

## SOC 与可用功率

业务侧 `P > 0` 为放电，`P < 0` 为充电，`h = duration_seconds / 3600`：

```text
放电：SOC_next = SOC - (P / eta_discharge) * h / capacity_kwh
充电：SOC_next = SOC + (-P * eta_charge) * h / capacity_kwh
```

例如 500 kWh 电池以 100 kW 放电 5 秒，SOC 减少约 `0.000292398`，即约 0.02924 个百分点；不能把 kW 当成 kWh，或漏掉秒转小时。

区间允许的充放电功率为三种限制的交集：

```text
charge_energy_limit = max(0, (soc_max - SOC) * capacity / (h * eta_charge))
discharge_energy_limit = max(0, (SOC - soc_min) * capacity * eta_discharge / h)
charge_limit = min(charge_energy_limit, 铭牌充电上限, 当前设备充电上限)
discharge_limit = min(discharge_energy_limit, 铭牌放电上限, 当前设备放电上限)
```

`power_limits` 返回 `(最大充电功率, 最大放电功率)`，两个数都非负。`project_soc` 不裁剪结果。当前与预测 SOC 共用 `SOC_TOL=1e-10`，容忍浮点边界舍入，但不会给电池新增可用电量。Schema 的绝对 [0,1] 范围与运行上下限是两层不同约束。

无自放电、温度动力学、老化、逆变器动态和自动待机能耗。一次批准只能用于其完整 duration，不能无限沿用。

## 单区间优化

非负变量：进口 `g_in`、出口 `g_out`、充电 `ch`、放电 `dis`、实际光伏 `pv`、普通削负荷 `shed`。

```text
g_in - g_out - ch + dis + pv + shed
    = critical_demand + normal_demand + loss_reserve

cost = h * [import_cost * g_in
            + curtail_cost * (pv_available - pv)
            + shed_cost * shed
            + battery_cost * (ch + dis)]
```

关键负荷没有削减决策变量。每个变量都有对应功率/能量边界。代码分别枚举“只允许充电”和“只允许放电”两个 LP，取较低目标的解，禁止同时充放电。每个 LP 的 HiGHS time_limit 为 5 秒；它不是整个云端任务的端到端超时承诺。

出口没有收益，进口成本为正；目标不是经过市场标定的电价模型，也没有未来负荷、终端 SOC 价值或跨周期最优性。`optimal` 只指当前简化 LP，不表示 AC 可行或系统级最优。

### 拒绝后的反馈

首轮 `loss_reserve=0`。AC 发现进口越限时，下一轮纳入上次损耗的 `1.10 * loss_kw + 0.02 kW`；其他已有收敛反馈至少带入该损耗。遇到低压或线路过载时，还把进口预算乘以 0.7。

这是有界启发式，**不是 AC OPF，也不保证所有物理可行情况都找到方案**。过压、反送电等情况没有完备的专用修复算法。反馈必须绑定同一个 state/config；再次失败仍要拒绝，而不是放宽安全门。

## 固定规则对照

缺口按“PV → 主网 → 储能 → 可削普通负荷”处理；富余 PV 按“充电 → 允许的出口 → 弃光”处理。复用相同电量约束和反馈预算，但不调用 LP。返回 `feasible` 候选，仍必须通过 Validator；`objective` 为 null，不能拿 null 与优化成本直接比较。

## 数值容差与适用边界

Validator 的 PCC/功率平衡容差为 0.02 kW，储能功率比较容差为 1e-8 kW；SOC 容差为 1e-10。执行审计还核对时长、实际设定值和证据绑定。这些是软件数值约定，不是允许真实设备突破保护阈值的工程结论。

模型为单区间、两母线、准稳态。完全失联网侧没有参考节点与构网电源，因此明确不支持孤岛；不模拟不平衡三相、短路、频率响应、真实停电过程或硬件执行延迟。

## 官方实现参考

- [pandapower storage 符号与 SOC](https://pandapower.readthedocs.io/en/stable/elements/storage.html)
- [pandapower external grid / PF 与 OPF](https://pandapower.readthedocs.io/en/stable/elements/ext_grid.html)
- [SciPy linprog](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html)

以上为第三方库行为参考；业务约束、参数和启发式以本仓库代码为准。升级记录见[依赖文档](dependencies.md)。
