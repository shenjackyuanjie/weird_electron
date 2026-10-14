# weird_electron / GridGuardian Power

GridGuardian 实施计划 **§8.2 B：电力算法线** 的第一版本地实现。范围以计划 §2 的无 Agent 闭环为主：

```text
事故注入 → 读取状态 → SciPy 调度优化 → 独立规则与 pandapower AC 校验
                              ↑ 不通过，带原因重规划一次 ↓
                  accepted → 下一仿真步执行 → applied / 新状态
```

**这不是已接入华为云的成品，也不是生产级电网保护系统。** AgentArts、IoTDA、实际 MCP Server、云后端和前端由 A/C 线继续接入；这里提供它们需要调用的内部算法和 JSON 接口。

## 快速开始

支持 Python **3.11–3.13**，无需大模型密钥或云账号。

```bash
python -m venv .venv
# Windows PowerShell：.venv\Scripts\Activate.ps1
# Linux/macOS：source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
python -m pytest -q
python -m simulator demo --scenario A --output outputs/demo-A
```

也可不进行 editable 安装，直接在仓库根目录运行 `python -m simulator` 和 `python -m pytest`。
若使用较旧 pip，请先更新 pip/setuptools；源目录运行方式不依赖 editable 构建。

## 已实现

| 模块 | 入口 | 作用 |
|---|---|---|
| 共享协议 | `power_engine/contracts.py` | Pydantic、有限数值、单位、状态/方案指纹 |
| SOC | `power_engine/battery.py` | 容量、效率、时间积分、能量/铭牌/降额功率交集 |
| 潮流 | `run_power_flow(state, plan, config)` | 真正的 pandapower 交流潮流、电压、线路负载、损耗 |
| 优化 | `optimize_dispatch(state, config, feedback=...)` | 两种充放电模式分别求 LP，绝不同时充放电 |
| 安全校验 | `validate_plan(state, plan, config)` | 硬规则 + AC 复算，检查实际 PCC 交换功率 |
| 固定规则 | `fixed_rule_dispatch(...)` | 光伏优先，缺口按主网→电池→普通负荷削减处理 |
| 仿真器 | `MicrogridSimulator` | reset / trigger_scenario / get_state / apply_action / step |
| 本地控制环 | `control_step(simulator)` | 初次方案 + 最多一次重规划，无解/不安全则明确停止 |
| JSON 适配器 | `power_engine.api.invoke` | 提供后续 MCP/Backend 可包装的计算入口 |
| 实验 CLI | `python -m simulator` | A/B/C Demo、同 seed 两策略实验、CSV/JSONL/Schema 导出 |

## 三个标准场景

```bash
python -m simulator demo --scenario A --output outputs/demo-A
python -m simulator demo --scenario B --output outputs/demo-B
python -m simulator demo --scenario C --output outputs/demo-C
python -m simulator demo --scenario A --policy baseline --output outputs/baseline-A
python -m simulator batch --cases 40 --steps 4 --output outputs/batch
python -m simulator schemas --output outputs/schemas
```

A：PV 350→100 kW；B：PCC 进口上限 100→40 kW，**仍然并网**；C：ESS 放电上限 200→20 kW，并产生 `ESS_DERATED`。每个 Demo 包含正常运行、事故运行和恢复正常的时间段。默认每步 5 秒，但快速仿真不等待真实的五秒钟。

输出目录包含 `config.json`、`summary.json`、`trace.jsonl`；批量运行额外生成 `results.csv`。日志包含每次候选方案、拒绝原因和实际执行回执，失败案例同样保留。`demo` 未完成返回退出码 2；`batch` 允许随机不可行案例存在，并在 CSV 中明确标注。

**本仓库的 `optimizer` 是确定性优化对照，不冒充 Single-Agent 或 Multi-Agent。** 后两种策略需 A 线接入相同场景运行器后再评估。

## 给 A/C 线的最小接入示例

```python
from power_engine.api import invoke
from simulator.simulator import MicrogridSimulator

sim = MicrogridSimulator()
sim.trigger_scenario("A")
state = sim.get_state().wire()
proposed = invoke("optimize_dispatch", {"request_id": "demo-1", "state": state})
plan = proposed["result"]["plan"]
verdict = invoke("validate_plan", {"state": state, "plan": plan})
# 初始 LP 忽略损耗，可能被独立 AC gate 拒绝；参考 control_step 的一次重规划流程。
print(verdict)
```

调用返回 `ok=true` 只表示工具调用成功，不表示方案安全；检查优化 `status`、`plan` 是否为空，以及 `validation.pass`。
`apply_action()` 自己重新校验，不接受调用方伪造的“已经验证”。ACK 为 `accepted`，`step()` 才更新功率和 SOC 并产生 `applied`。每个方案只执行一个指定时长的区间，不能默默无限续期。

## 必须先理解的边界

模型是平衡三相、准稳态、单区间有功调度，不包含频率动态、真实设备保护或预测控制。`frequency_hz` 是额定输入，不是潮流计算出来的频率。

采用“上级电源—有阻抗馈线—微电网母线”的两母线等值模型，避免所有设备直接连接理想电压源导致电压永远不变。PCC 交换功率取馈线**上级端**，包含馈线损耗；`pcc_voltage_pu` 取**微电网端**，测量位置有意明确区分。

`grid_available=false` 明确返回 `UNSUPPORTED_ISLAND_MODE`：尚无构网型储能模型，不会伪造一个无限功率孤岛电源。文档允许 B 用限制 PCC 交换功率实现，本版选择该路径。

所有容量、线路参数、SOC 边界、功率因数和成本权重均是**演示假设**，详见 [模型假设](docs/model.md)，不是计划已经给定的设备参数或工程结论。直接依赖已固定版本，CI 每次导出完整 `pip freeze`，暂未提供跨平台全量锁文件。

## 继续开发

先看 [接口协议](docs/contracts.md)、[模型与限制](docs/model.md)、[后续接入清单](docs/handoff.md)。改字段先改协议。
CI 在 Linux/Python 3.11 与 Windows/Python 3.13 运行真实潮流测试，并上传测试结果、环境清单和 Demo/实验日志。

## 第二轮加固

当前版本增加了严格的时长/请求 ID 校验与贯穿工具调用的 request_id；Simulator 公开操作有实例级锁，并提供 `get_receipt(plan_id)`、`cancel_pending_action()`。`ExecutionReceipt.validation` 保存实际执行入口复验结果。

实验会独立核对实际执行的 SOC、储能功率、PCC、电压、线路、功率平衡和负荷/PV，输出 `execution_audit` 及能量统计。没有执行的区间不计算供电能量；不完整实验的完整周期保障率保持 null。`batch` 的合理无解样本仍保留，但运行故障或审计失败会返回非零退出码，根目录 `summary.json` 给出总体结果。

完整环境推荐运行 `python -m pytest --require-ac`：缺少真实 pandapower 或有任何跳过项都会失败；普通 `pytest` 仍支持在缺依赖的环境中只做明确标注的部分测试。三个 Demo 在 CI 中分别执行，任何一个失败都会使 job 失败。接口细节及改变原因见 [第二轮审查记录](docs/review-2026-10-14.md)。
