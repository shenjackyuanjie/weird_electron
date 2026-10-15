# GridGuardian B 线文档

本目录以仓库代码为“当前实现”的依据，以《GridGuardian 分阶段可实现路径计划》为“项目要求”的依据。默认参数、接口细化和部署建议不是原计划已冻结的事实。遇到差异要区分要求、实现和后续工作，不能只改文档宣称功能已完成。

## 首次 ABC 联合测试

按本轮队内通知，先看 [GridHive 光伏骤降：B 线接口交付](joint-test-b.md)。其中区分现有 API 与 C 遥测映射草案，并提供真实 AC PASS/REJECT 请求与返回的生成、重放方法；暂不扩展云服务或生产算法。

## 建议阅读顺序

首次使用：[安装与 CLI](getting-started.md) → [场景](scenarios.md) → [实验输出](experiments.md)。

开发 B 线：[架构](architecture.md) → [模型](model.md) → [协议](contracts.md) → [API](api.md) → [测试](testing.md)。

接入 A/C 线：[协议](contracts.md) → [API](api.md) → [交接](handoff.md) → [排错](troubleshooting.md)。

维护环境：[依赖](dependencies.md) → [测试](testing.md)。历史记录：[第二轮审查](review-2026-10-14.md)。

## 与实施计划对应

| 原计划章节 | 仓库交付 | 边界 |
|---|---|---|
| §2.1 Simulator / SOC / 事故引擎 | `simulator/`、`power_engine/battery.py` | 外部条件为预设分段常量；不是连续气象或动态电磁仿真 |
| §2.2 潮流 / 优化 / 独立校验 | `power_flow.py`、`optimizer.py`、`validator.py` | LP 加 AC 校验，不是 AC OPF |
| §2.3 无 Agent 闭环 | `control_step`、Demo、集成测试 | 默认一次重规划；不可行时停表，不编造恢复 |
| §2.4 固定运行环境 | requirements、pyproject、四环境 CI、wheel | 固定直接依赖；完整传递锁文件尚未提供；未声称已部署 ECS |
| §7.1–7.3 对照与指标 | 固定规则/确定性优化配对实验、执行审计、能量积分 | 不是三套 Agent 对照；没有云事件端到端耗时 |
| §8.2 B 对外边界 | JSON/Pydantic、内部函数、示例 | 不暴露 pandapower 网络对象 |
| §3–6 云端、多 Agent、展示 | 交接说明及预留目录 | 尚未实现，不在本轮文档补全中冒充交付 |

原计划 §8.1 有“调用 A 提供的确定性工具”的表述，而 §8.2 把算法归给 B。本仓库按 §8.2 实现算法；MCP 封装及部署归属仍由集成负责人确认，不能把上述歧义默默改写成已达成共识。

## 文档维护约定

`power_engine/contracts.py` 是可执行 Schema 定义，`docs/contracts.md` 解释语义。先约定字段再修改模型，同时更新示例、生成 Schema 和测试。示例默认来自代码运行，不手写伪造的 SHA-256、审批回执或“成功”结果。

`tests/test_documentation.py` 检查相对链接、依赖声明一致性以及两个真实运行示例。运行后生成的 Schema 位于 `outputs/schemas/`，不要把旧导出长期当成最新协议。

版本和验证结果按日期、commit、CI run 记录。历史测试成绩不自动适用于新提交；不将“没有执行”写成“安全运行”，也不将“校验通过”写成“已经执行”。
