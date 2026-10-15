# B 线首轮联调材料：验证记录（2026-10-15）

[接口交付说明](joint-test-b.md) · [固定 JSON 案例](../examples/joint-pv-drop.verified.json)

已测提交：`06ade92293645bb2e7794f3179c6597575210db7`。对应 [Power engine tests #7](https://github.com/shenjackyuanjie/weird_electron/actions/runs/38754584827)。四个 job 均 completed/success，已下载核对各自 JUnit、coverage、Demo 和生成的 JSON；这不是据 CI 绿色图标推测测试数量。

| 环境 | 通过 | 失败/错误/跳过 | 语句覆盖率 |
|---|---:|---:|---:|
| Ubuntu / Python 3.11 | 241 | 0/0/0 | 95.08% |
| Ubuntu / Python 3.12 | 241 | 0/0/0 | 95.08% |
| Ubuntu / Python 3.13 | 241 | 0/0/0 | 95.08% |
| Windows / Python 3.13 | 241 | 0/0/0 | 95.08% |

新增 11 项专门的联调样例测试，另有 2 项来自既有文档检查的参数化扩展。没有更改 power_engine、simulator 生产代码、依赖和 CI 权限。各环境均完成真实 AC、原有 A/B/C Demo、Schema、安装检查和 wheel；Ubuntu 3.11/3.13 的原有批量回归各为 80 次中 78 次完成，2 次明确无解，运行故障/已执行越界均为 0。这些旧场景用于回归，不是扩大本轮联合测试范围。

## 首次联调专用案例

同一份完整 state/config：PV 已由 350 降到 100 kW，关键负荷 200、普通负荷 150、禁止削负荷、SOC 0.6、主网进口上限 100、储能最大放电 200 kW。每个候选覆盖 5 秒。

| 案例 | 储能放电 kW | 实际 PCC 进口 kW | PCC 电压 p.u. | 结果 |
|---|---:|---:|---:|---|
| 初次优化 | 150.0 | 100.95819505617776 | 0.9908228603124772 | REJECT：GRID_IMPORT_LIMIT，AC 实际收敛 |
| 同状态带反馈重规划 | 151.07401456180037 | 99.87044858527838 | 0.9908912160874248 | PASS，完整 AC 校验通过 |
| 人工储能越限 | 201.0 | 未计算 | 未计算 | REJECT：ESS_DISCHARGE_LIMIT；power_flow=null |

PASS 的 `normal_shed_kw=0`、`critical_shed_kw=0`、`pv_power_kw=100`。预测区间结束 SOC 为 `0.5995582631153163`；这是 B 的预测，不是 C 的真实执行结果。实际请求/返回中保留未舍入数值、plan_id、request_id 和三类指纹。四环境均复现该功率方案和通过/拒绝判定。

## JSON 在哪里、怎么使用

CI 的 `outputs/joint-pv-drop/` 含 14 个 JSON：完整 config/state、三种案例请求与返回、初次/重规划请求与返回、bundle，以及明确标注为 proposal 的 C 遥测草案。Linux 3.12 artifact `11983440720` 是本次归档静态案例的来源；其他环境 artifact 为 Ubuntu 3.11 `11982577903`、Ubuntu 3.13 `11983271719`、Windows 3.13 `11982807633`。

仓库的 `examples/joint-pv-drop.verified.json` 去除了重复 state/config，但没有改动任何 plan 或 ValidationResult 内容。它是方便离线查看的已验证固定样例，不是新的 API 外壳。按以下方式构造现有 Validator payload：

```python
import json
from pathlib import Path
from power_engine.api import invoke
from power_engine.contracts import MicrogridConfig

sample = json.loads(Path("examples/joint-pv-drop.verified.json").read_text(encoding="utf-8"))
config = MicrogridConfig.model_validate(sample["config"])
for name, case in sample["cases"].items():
    payload = {"state": sample["state"], "plan": case["plan"]}
    reply = invoke("validate_plan", payload, config)
    assert reply["ok"]
    assert reply["result"]["pass"] == case["validation"]["pass"]
    print(name, reply["result"]["pass"])
```

所有静态案例再次经过本地 Pydantic 与状态/方案/配置指纹校验；AC 判定来自上述真实 CI 及其中的 JSON 重放测试。本文件和静态 JSON 为验证结束后的归档补记，没有改变已经测试的代码。静态固定时间不可当成当前遥测，固定 plan_id 不可当成生产命令。

## 还没有被本轮证明的事情

未调用 C 的状态读取、IoTDA 命令或真实设备；未重复验证 A 的 AgentArts 部署；没有生成 C 的 applied 回执。因此只能称为“B 线联调准备完成、离线契约与 AC 案例已验证”，不能称为“ABC 联合闭环已完成”。下一步是对齐 C 的原始响应、单位/时钟/在线状态、设备档案、指令精度与时长、ACK/执行后遥测，以及 A 的 MCP 封装字段。
