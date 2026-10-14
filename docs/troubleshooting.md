# 排错手册

[文档首页](README.md) · [协议与错误层](contracts.md) · [安装](getting-started.md)

## 先保留证据

出现问题先保存完整 error_code/message、request_id/plan_id、当前状态、配置、候选/实际回执、git SHA 与 pip freeze。不要只截 Dashboard 的一个数值，也不要为了复现前先 reset 清空回执。

```bash
python --version
python -m pip --version
python -m pip check
python -m pip freeze
git rev-parse HEAD
python -m pytest --require-ac -x
```

不要把凭据、完整真实用户遥测或无关内网信息粘到公开 issue。

## 环境与安装

| 症状 | 核查与处理 |
|---|---|
| `ModuleNotFoundError: pandapower` / `DEPENDENCY_UNAVAILABLE` | 确认运行的是安装依赖的同一个虚拟环境；执行 requirements-dev 安装和 pip check。不能切换到假潮流后宣称集成通过 |
| pip 报 Requires-Python / 无匹配版本 | 本仓库支持3.11–3.13；不要强行安装 SciPy1.18 到3.11；环境 marker 会选兼容分支 |
| pip 报 NumPy/Pandas 冲突 | 最新 pandapower 仍限制 NumPy<2.5、Pandas2.x；新建环境按仓库 pins 安装，不能用 --no-deps 绕开 |
| PowerShell 禁止 Activate.ps1 | 直接使用 `.\.venv\Scripts\python.exe`，无需降低整台机器的脚本执行策略 |
| `gridguardian` 找不到 | 先 editable 安装；或在仓库根目录运行 `python -m simulator` |
| `examples` 找不到 | 示例只随源仓库提供，不包含在 runtime wheel；在源仓库根目录运行 `python -m examples.local_loop` |
| 下载超时或索引暂未同步 | 检查实际 pip index 和网络；使用可信、已同步的索引。不要用关闭 TLS 校验代替排错 |
| 测试显示 skipped | 可能缺少真实 AC 依赖；验收使用 --require-ac，不能把“纯逻辑通过”说成完整通过 |

本轮 CI 没有验证 macOS、ARM、PyPy 或 CPython3.14。未验证不等于已确认不兼容，但不能声称已支持。

## 输入、追踪与计划

| code / 现象 | 意义 | 下一步 |
|---|---|---|
| INVALID_INPUT | Schema/字段/类型不合法 | 时长传数值5，不是"5"或true；request_id非空字符串；state/plan形状分别正确；检查错误文本字段路径 |
| UNKNOWN_TOOL | JSON 适配器没有该工具 | 只支持 optimize_dispatch、run_power_flow、validate_plan；执行走可信 Simulator/后续执行服务 |
| request_id冲突 | 外层ID不等于plan.request_id | 使用plan的ID或省略外层；不要为同一调用链随意换ID |
| STALE_FEEDBACK | 反馈属于别的state/config | 丢弃旧反馈，从最新状态开始规划 |
| STALE_STATE | 计划/批准绑定的状态不再当前 | 重读状态重新规划，不要手改fingerprint伪装成新计划 |
| IDEMPOTENCY_CONFLICT | 相同plan_id有不同内容 | 重规划必须生成新plan_id；不能改内容后复用旧ID |

`ok=true` 但 plan=null、converged=false 或 pass=false，不是适配器异常：工具调用成功与业务结果是两层。按嵌套 status/error_code/violated_rules 处理。

## 接收与执行

| code / 现象 | 意义 | 下一步 |
|---|---|---|
| ACTION_PENDING | 还有未执行命令 | 查询其回执，执行原计划或显式取消，再提交新ID |
| NO_PENDING_ACTION | 没有待执行安全方案 | 先完整规划与校验，再apply_action；不能直接无限step |
| DURATION_MISMATCH | step时长与校验时长不同 | 按原时长执行；需要改时长就取消并重新规划 |
| STALE_CONFIG | 接收后可信配置改变 | 取消pending，用明确的新配置/状态重新规划；不要沿用旧审批 |
| UNSAFE_PLAN | 实际执行入口拒绝候选 | 即便之前通过也要检查最新状态；保留规则code，不跳过复验 |
| cancelled回执再次返回 | 同ID同内容幂等地返回终态 | 这是预期行为；新命令需要新ID |
| get_receipt返回None | 当前实例没有该记录 | 检查是否reset/换实例/进程重启；它不证明外部硬件没执行过 |

无效step不会推进模拟时间，也不会自动取消pending。`cancel_pending_action()` 返回取消回执或None；`trigger_scenario` 会自动取消待执行命令。`reset` 会清空内存回执，因此不要把它当作无损取消操作。

## 电力无解与安全拒绝

NO_FEASIBLE_DISPATCH 表示当前简化调度约束下无解。先比较可用PV、PCC能力、受SOC/时长限制后的电池能力，是否足以满足不可削负荷；容量很大不代表当前SOC还能放电。只有普通负荷允许削减，关键负荷不是兜底调节项。

GRID_IMPORT_LIMIT 常见于首轮LP未计馈线损耗：传入同状态/配置的validation反馈重规划。VOLTAGE_LOW/LINE_OVERLOAD有缩小进口预算的启发式，但并非完备AC优化；高压或反送电也可能仍被拒绝。VALIDATION_REJECTED不等于已证明物理绝对无解，只说明有限尝试没有拿到安全方案。

SOC_MIN/SOC_MAX/CURRENT_SOC_LIMIT需检查单位（0–1不是0–100）、充放电方向、时长和效率。不要加大容差或把SOC裁回范围掩盖能量错误。

UNSUPPORTED_ISLAND_MODE不是偶发崩溃：完全断网尚无构网型储能/孤岛参考模型。B场景应使用仍并网的PCC功率限制，不要人为加入无限容量电源来“修复”。

POWER_FLOW_FAILED/INVALID_POWER_FLOW_RESULT需查看具体message及输入，确认线路参数、求解环境和非有限结果；OPTIMIZER_FAILED可能是求解器异常或达到限制。这些是运行错误，不应在批量实验中伪装成合理无解。

## 日志与指标

初始/事故后的PCC功率和电压为null是“尚未求出新运行点”，不是0或已安全。完整周期比率为null可能是episode未完成或分母为0；CSV空白不能填成100%。

EXECUTION_AUDIT_FAILED、MISSING_EXECUTION_VALIDATION等代表实际证据缺失或不一致：保存现场并停止对结果作安全声明。若人工修改过trace，先回到原始产物；不要重新计算一个候选批准替换执行回执。

`batch`退出0仍可能存在无解/有限次拒绝，查看summary.incomplete与每行failure_kind。重用旧输出目录后看到残留seed，应换新目录重跑，而不是把多轮不同参数的子目录混为一次实验。

后续HTTP/MCP/IoTDA连接错误不是当前本地CLI可修复的部分，服务端适配与权限边界见[集成交接](handoff.md)。
