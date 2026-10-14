# weird_electron / GridGuardian Power

GridGuardian 实施计划 **§8.2 B：电力算法线** 的本地实现。这个仓库是 Python 项目，名称里的 electron 不代表 Electron 桌面应用。

它模拟光伏、弱主网 PCC、储能、关键负荷和普通负荷，并运行以下无大模型闭环：

```text
读取状态 → 确定性调度 → 独立硬规则 + 真实 AC 潮流校验
                   ↑ 拒绝后最多重规划一次 ↓
      apply_action（accepted，保存执行入口复验）
                   ↓
      step（推进一个区间，applied，更新 SOC/功率）
                   ↓
      执行后审计 → JSONL / CSV / 下一轮状态
```

**这是阶段二的准稳态软件微电网，不是已接入华为云的完整产品，不可用于真实设备自动控制。** MCP、IoTDA、AgentArts、云后端和 Dashboard 仍是后续集成工作；本仓库不伪造这些服务的结果。

## 第一次运行

支持 CPython **3.11–3.13**。推荐新环境使用 3.13；SciPy 在 3.11 下使用兼容分支，详见[依赖版本](docs/dependencies.md)。需要 GitHub 仓库读取权限，但运行不需要云账号或模型密钥。

```bash
git clone https://github.com/shenjackyuanjie/weird_electron.git
cd weird_electron
python -m venv .venv
# Linux/macOS：source .venv/bin/activate
# Windows PowerShell：.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
python -m pip check
python -m pytest --require-ac
python -m simulator demo --scenario A --output outputs/demo-A
```

不希望激活 Windows 虚拟环境时，把上述 `python` 换成 `.\.venv\Scripts\python.exe`。完整系统分步说明、升级旧环境和仅运行安装见[安装与 CLI](docs/getting-started.md)。

Demo 成功时 `complete=true`，默认完成 6 个五秒区间。这里是仿真时间，程序不等待真实五秒。查看 `outputs/demo-A/summary.json` 和 `trace.jsonl`；不要只看进程有没有启动。

## 文档导航

| 需要做什么 | 从这里开始 |
|---|---|
| 找到所有文档、理解原计划与实际实现的边界 | [文档首页](docs/README.md) |
| 安装、运行三个事故、配置参数、导出 Schema | [安装与 CLI](docs/getting-started.md) |
| 阅读模块、数据流和命令状态机 | [架构与执行语义](docs/architecture.md) |
| 理解电力模型、SOC、LP、默认参数与适用范围 | [模型与数学约定](docs/model.md) |
| 对齐字段、单位、ID、错误及 JSON 格式 | [数据协议](docs/contracts.md) |
| 从 Python 或 JSON 适配器调用算法 | [API 与完整示例](docs/api.md) |
| 触发事故、恢复和复现场景 | [场景说明](docs/scenarios.md) |
| 解释 CSV、拒绝、越界、失败样本和耗时 | [实验与指标](docs/experiments.md) |
| 修改代码、运行测试、查看 CI | [开发与验证](docs/testing.md) |
| 定位安装失败、无解、过期命令等问题 | [排错手册](docs/troubleshooting.md) |
| 交给 A/C 线、部署到 ECS 前确认职责 | [集成交接](docs/handoff.md) |
| 查看升级策略、版本来源与兼容例外 | [依赖与升级记录](docs/dependencies.md) |

## 常用命令

在仓库根目录执行；安装 editable 后也可用 `gridguardian` 替代 `python -m simulator`。

```bash
python -m simulator demo --scenario B --output outputs/demo-B
python -m simulator demo --scenario C --output outputs/demo-C
python -m simulator demo --scenario A --policy baseline --output outputs/baseline-A
python -m simulator demo --scenario A --config examples/demo-config.json --output outputs/custom
python -m simulator batch --cases 40 --steps 4 --output outputs/batch
python -m simulator schemas --output outputs/schemas
python -m examples.local_loop
python -m examples.manual_dispatch
```

`demo` 不完整退出 2。`batch` 保留合理无解的样本，但运行故障或执行审计失败退出 2。**退出 0 不等于所有随机样本完成。** 输出目录会覆盖同名文件，保留实验时使用不同目录。

## 已实现与明确未实现

已实现真实 pandapower 平衡三相 AC 潮流、SOC 能量约束、SciPy/HiGHS 单区间优化、独立 Validator、三类事故、固定规则对照、事务式单区间执行、单实例并发保护和执行证据审计。

当前 B 场景采用“仍并网、限制 PCC 交换功率”。`grid_available=false` 返回 `UNSUPPORTED_ISLAND_MODE`；没有构网型储能、频率动态、不平衡三相、短路/暂态保护、持续后台设备循环或多进程持久化。所有默认电气与成本参数都是演示假设，需要团队审核。

`optimizer` 与 `baseline` 都是确定性策略，不是 Single-Agent/Multi-Agent。最新验证证据见[测试说明](docs/testing.md)和[依赖记录](docs/dependencies.md)；历史审查结果见[第二轮审查](docs/review-2026-10-14.md)。
