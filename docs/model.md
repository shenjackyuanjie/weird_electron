# 模型、数值约定与已知限制

## 计划规定与本次假设分开

计划明确：五类对象、5 秒仿真步、离散 SOC、pandapower 潮流、PuLP/scipy 优化、独立校验、A/B/C 三类事故、一轮本地重规划和固定规则 Baseline。计划未给出容量、线路参数、效率、负荷水平、调度权重及电压运行边界。

本版默认假设：500 kWh ESS；SOC 0.1–0.9，初始 0.6；双向效率 0.95；充电 150 kW / 放电 200 kW；PV 350 kW；关键负荷 200 kW、普通负荷 300 kW；PCC 进口 100 kW、出口 0；0.4 kV；80 m 馈线，R=0.125 Ω/km、X=0.08 Ω/km、最大 0.6 kA；负荷功率因数 0.98；允许电压 0.95–1.05 p.u.、线路 100%。这些数值仅用于演示，需要团队审核。

网络提供上级参考母线和微电网 PCC 两个母线；四个下游设备均位于 PCC。馈线代表弱连接，不新增新的能源类型。储能/PV 无功设为 0，负荷无功按固定功率因数计算，上级网络承担无功。

## SOC

业务侧 P>0 放电：

```
SOC_next = SOC - (P / eta_discharge) * seconds / (3600 * capacity_kwh)
```

P<0 充电：

```
SOC_next = SOC + (-P * eta_charge) * seconds / (3600 * capacity_kwh)
```

不裁剪越界结果。优化约束、Validator 都使用完整计划时长的能量边界，最终执行复用相同能量模型。不含自放电、温度动力学、老化或恒功率之外的电池模型。

## 优化

单时间段，两次 HiGHS LP 分别只允许充电/放电，选成本更小的可行解。变量是进口、出口、充电、放电、实际 PV、普通负荷削减；负荷平衡包含来自上一轮 AC 拒绝反馈的损耗预算。无出口收益；进口成本为正，避免同时进口/出口套利。

目标：购电 + 弃光惩罚 + 削普通负荷惩罚 + 电池吞吐成本。不是经过市场标定的价格模型，不包含未来电价/天气/终端 SOC 价值。跨周期经济性和真正 MPC 留待后续。

第一轮有功平衡不含馈线损耗，饱和 PCC 候选可能被 AC gate 拒绝。收到 GRID_IMPORT_LIMIT 后，将上轮实际损耗的 110% + 0.02 kW 纳入新平衡以留余量；低电压/过载重试把进口预算降至 70%。这只是一次重规划启发式，**不是 AC OPF，不保证为所有物理可行问题找到方案**。第二轮仍不通过就停止/交给上层人工处理，不放宽 Validator。

AC 检查 PCC 实际功率，不能依赖 pandapower ext_grid 的 max_p_mw；普通潮流不会执行 OPF 功率边界。功率数值容差 0.02 kW、SOC 容差 1e-10，不应解释为可在生产中超越保护阈值。

## 仿真与指标

外部条件在一个区间内保持不变。CLI 调度预设的正常→事故→恢复序列，非连续天气模型。注入事故只改变约束/可用出力，不自动把系统“恢复”到预期答案；只有通过校验并执行后才产生新的电力状态。

每个 episode 正常第一步、第二步注入事故、最后一步恢复正常参数。步数最少为 3。`critical_supply_ratio`、`pv_utilization_ratio` 按实际完成区间的能量积分；若整场实验失败，汇总比例为 null，避免部分成功掩盖失败。保留已执行状态与所有失败原因。失败后仿真停表，不声称获得真实停电能量估计。

`executed_constraint_violations` 检查执行后的 SOC、PCC 和关键负荷；详细电压/线路判定保留在每个 validation.power_flow 中。它尚不是实施计划 §7.3 全部指标的最终统一实现。`local_control_latency_ms` 是本地计算耗时，不是云端事件到执行延迟。随机场景和相同 seed 配置用于 baseline/optimizer 配对，UUID 和耗时不要求逐字节一致。

## 明确不支持

孤岛/构网、频率响应、不平衡三相、故障短路/电磁暂态、真实设备通信、并发公开服务、鉴权、持久化 Gate、LLM、多智能体能力评估。不得用于真实电网自动控制。

## 官方实现参考

- pandapower storage（符号和 SOC 不自动推进）：https://pandapower.readthedocs.io/en/stable/elements/storage.html
- pandapower external grid（参考节点、普通 PF 与 OPF 约束区别）：https://pandapower.readthedocs.io/en/stable/elements/ext_grid.html
- SciPy linprog / HiGHS：https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html
