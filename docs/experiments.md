# 实验、日志与指标解释

[文档首页](README.md) · [场景与复现](scenarios.md) · [开发与验证](testing.md)

## 对照范围

本仓库比较固定规则 `baseline` 与确定性 LP `optimizer`，两者都经过同一 Validator、Simulator 执行入口和执行后审计。它们不是原计划 §7.1 的 Single-Agent 或 Multi-Agent；接入 Agent 后才能补齐三套系统对照。

```bash
python -m simulator batch --cases 40 --steps 4 --output outputs/batch
```

40 个 seed 对应 80 个 episode。每对使用相同初始配置、事故类型和 severity。种子不固定 UUID、机器耗时或不同求解器版本的末位浮点差异。保存代码 SHA、依赖 freeze、config、seed、severity 和全部 trace，不能只留 CSV。

## 输出结构

```text
outputs/batch/
    summary.json
    results.csv
    seed-000-baseline/
        config.json
        summary.json
        trace.jsonl
    seed-000-optimizer/
        ...
```

`config.json` 是初始配置；批量 episode 的 summary 额外记录 `seed`、`severity_kw`。单独 `write_episode` 不自动保存调用者未写入 summary 的 severity，定制实验要自行保留。重复使用输出目录会覆盖同名文件；减少 cases 后旧子目录也可能残留，应为每次实验使用新的目录。

### trace.jsonl

每行是一轮 `control_step` 的结果，附本地计算耗时。公共字段包括 `success`、`before`、`state`、`attempts`、`operational_error` 和 `local_control_latency_ms`。

`attempts` 每项有 `plan`、`validation`、`optimization_status`、`objective`。无可行候选时 attempts 可以为空。成功行还有 `receipt` 和实验运行器追加的 `execution_audit`；失败行有 `error_code`，可能有 `message` 或 `optimization`。

候选 validation 和 `receipt.validation` 必须区分：后者来自 **apply_action 的实际复验**。执行审计只使用实际回执证据，不把候选通过当成执行证明。`execution_audit.violated_rules` 是 code 字符串列表，而 candidate validation 中是含 code/message/actual/limit 的对象列表。

读取 JSONL：

```python
import json
from pathlib import Path

path = Path("outputs/demo-A/trace.jsonl")
for line in path.read_text(encoding="utf-8").splitlines():
    event = json.loads(line)
    print(event["success"], len(event["attempts"]), event.get("error_code"))
```

## episode summary / CSV 字典

| 字段 | 定义 |
|---|---|
| `complete` | 所有 requested_intervals 完成且没有执行审计失败 |
| `requested_intervals` / `completed_intervals` | 计划运行和实际成功执行的区间数 |
| `observed_duration_seconds` | 实际执行区间的时长之和，不包括失败后的想象时间 |
| `failure_kind` | none / infeasible / validation_rejected / operational_error / safety_violation |
| `operational_error` | 控制调用是否遇到已分类的运行错误；审计失败另有 safety_violation |
| `error_code` | 不完整原因；成功为 null |
| `rejected_candidates` | 实际验证记录中 pass=false 的候选数，不是已执行坏计划数 |
| `executed_constraint_violations` | 执行后审计不通过的区间数；一个区间多条违规只计一次 |
| `execution_constraint_violation_rate` | 上项 ÷ completed_intervals；分母为零时 null |
| `critical_requested_kwh` / `critical_served_kwh` | 观测区间内关键负荷需求/实际供电能量 |
| `pv_available_kwh` / `pv_used_kwh` | 观测区间内可用/实际采用 PV 能量 |
| `critical_supply_ratio` | 仅完整 episode 且需求能量非零时为 served/requested，否则 null |
| `pv_utilization_ratio` | 仅完整 episode 且可用 PV 能量非零时为 used/available，否则 null |
| `final_soc` | 停止时 Simulator 的 SOC，不外推到计划终点 |
| `max_local_control_latency_ms` | 本 episode 中单轮本地控制调用最大耗时 |

### 能量积分与空值

对每个已执行区间取 `h = plan.duration_seconds / 3600`：

```text
critical_requested_kwh += before.load_critical_kw * h
critical_served_kwh    += after.critical_served_kw * h
pv_available_kwh       += before.pv_available_kw * h
pv_used_kwh            += after.pv_power_kw * h
```

不完整 episode 仍保存已观测的能量，但完整周期比率保留 null。CSV 中 null 表现为空单元格，不是零，也不应填成 100%。例如先正常执行一段，事故后无解，不能据正常段供电充足而声称事故全过程关键负荷保障率为 100%。

PV 使用量包括本地负荷、储能充电及允许的反送电消纳，不等同于全部被本地关键负荷消耗。容量、功率、能量的单位不能混算。

### 越界与拒绝是不同维度

候选因线路损耗导致 PCC 越限，被 Validator 拒绝并重规划，是安全门工作的证据；它不增加已执行越界数。已执行审计检查 SOC、能量变化、储能能力、PV、负荷、PCC、母线电压、线路负载、功率平衡和状态/配置/方案/回执绑定。

分母采用实际执行区间数，而不是全部候选数。可视化或写竞赛报告时必须说明这一口径，避免靠生成很多被拒候选稀释越界率。

`rejected_candidates` 不是原计划的“不安全计划拦截率”。后者需要先构造带已知标签的不安全样本，分子为正确拒绝数、分母为构造总数；回归测试覆盖这类情况，但当前 batch CSV 不直接输出该比率。

### 耗时范围

local_control_latency 从本地控制调用开始到返回，包含规划、重试、校验、提交和 step；不包含之后的执行审计、磁盘写入或云端网络。首次 import 的开销和运行环境会影响它。

它不是“FunctionGraph 检测事件 → IoTDA 实际执行”的端到端耗时。模拟 timestamp 的推进也不是运行性能。当前没有 MCP 工具成功率、Agent 结构化通过率或 AgentArts Trace 指标。

## 失败分类与退出码

合理无解 (`NO_FEASIBLE_DISPATCH`) 记 infeasible；有候选但有限次校验仍不通过记 validation_rejected；缺依赖、求解器异常、状态失效等记 operational_error；实际执行审计失败记 safety_violation。

`demo` 未完整完成返回退出码 2。`batch` 仅在 operational_errors 或 executed_constraint_violations 非零时返回 2；合理无解和有限重规划后拒绝会保留，但不令进程失败。**batch 退出 0 不表示全部样本成功或算法完备。** 调用方还要看 complete/incomplete 和 failure_kind 分布。

失败后模拟器不继续推进时间、不生成新能量。因此这套实验不能回答未建模停电过程的实际未供电量。需要该指标时先定义对应物理模型，而不是修改统计字段作近似成功。

## 如何做可靠比较

比较前核验每对 config、事故值和区间时长一致，保留失败分母，并分别报告完成率、已执行越界、观测能量及耗时分布。不要把固定规则的 objective=null 与 LP 目标值直接当同口径成本比较；目前没有独立统一的实际运行成本报表。

本轮依赖升级在两条 SciPy 路径上复测了默认 40 seed：各 80 次实验中 78 完成、2 个相同低 SOC 供电不足案例被拒绝，运行故障和已执行越界均为零。此结果来自特定演示配置，不证明 LP 策略普遍优于固定规则，也不是对真实电网的安全认证。日期、提交与证据见[依赖升级记录](dependencies.md)。
