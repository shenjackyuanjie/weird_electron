# 开发、测试与验证证据

[文档首页](README.md) · [依赖升级](dependencies.md) · [API](api.md)

## 完整本地验证

先按[安装说明](getting-started.md)安装开发依赖，在仓库根目录执行：

```bash
python -m pip check
python -m ruff check .
python -m pytest --require-ac --strict-markers --cov=power_engine --cov=simulator --cov-report=term-missing --cov-fail-under=89
python -m simulator demo --scenario A --output outputs/demo-A
python -m simulator demo --scenario B --output outputs/demo-B
python -m simulator demo --scenario C --output outputs/demo-C
python -m simulator batch --cases 40 --steps 4 --output outputs/batch
python -m simulator schemas --output outputs/schemas
python -m examples.local_loop
python -m examples.manual_dispatch
python -m pip wheel --no-deps --no-build-isolation . --wheel-dir dist
```

`--require-ac` 是本仓库 tests/conftest.py 定义的选项：必须安装真实 pandapower，缺少时退出 4，测试阶段出现跳过也不能视作完整通过。开发时 `python -m pytest -m "not integration"` 可只测纯逻辑，但它不是交付验收；不要在该命令上同时要求完整 AC 覆盖率。

### 主要测试文件

| 测试组 | 重点 |
|---|---|
| `test_battery.py` | 充放电方向、秒/小时换算、能量和功率边界 |
| `test_contracts_validator.py` | Schema、硬规则、适配器基本错误 |
| `test_optimizer.py` | 两策略的候选、容量限制、不可行场景 |
| `test_integration.py` | 真实 AC、三类事故与完整执行闭环 |
| `test_review_regressions.py` | 非对象 JSON、SOC 浮点边界及连续真实执行 |
| `test_api_boundary.py` | 时长类型、request_id、冲突与一致性 |
| `test_execution_safety.py` | 并发提交/step、取消、配置失效、实际 gate 证据 |
| `test_execution_metrics.py` | 实际观测越界、能量及证据绑定审计 |
| `test_cli_failures.py` | 无解与运行错误区分、空值比率、CLI 退出行为 |
| `test_documentation.py` | Markdown 相对文件链接、Python 片段语法、依赖声明一致、配置与真实运行示例 |

并发和错误注入单元测试可以使用明确标注的人工 gate，以隔离事务行为；integration 必须使用真正 pandapower。测试用小容量/极端参数是构造边界的方法，不是项目默认设备参数。

## 修改流程

先写能触发原问题的回归测试，再改代码，最后跑完整套件和 Demo。改变模型或协议时同步 docs/contracts.md、接口示例、默认配置/Schema 导出与集成说明。

不要为了通过测试放大 SOC/PCC 容差、删除失败 seed 或把真实 AC 改成代数假结果。浮点比较应使用明确单位和容差；UUID 与计时不应要求跨运行字节一致。

新增场景、核心云服务或 Agent 不是顺手补代码的范围，应先与集成负责人确认。直接 main 提交也应保留可读的 commit 信息和验证证据。

## 当前 CI

`.github/workflows/tests.yml` 运行四个环境：Ubuntu CPython 3.11/3.12/3.13，Windows CPython 3.13。3.11 使用兼容 SciPy 分支，3.12/3.13 使用较新分支。

每个环境检查依赖安装、editable 安装、pip check、真实数值依赖、Ruff、完整测试（禁止跳过、coverage ≥89%）、三个独立 Demo、七类 Schema 和 wheel 构建。Ubuntu 3.11 与 3.13 分别跑 40 seed × 两种策略，覆盖两条 SciPy 路径。

四个 artifact 以 `power-tests-<os>-py<version>` 命名，包含 outputs、coverage.xml、requirements-resolved.txt 和 dist。JUnit 给出测试数/失败/跳过；trace 保存实际执行证据；outdated.json 是需要解释的包版本差异，不是要求无条件全部升级的清单。

wheel 构建通过证明可打包，editable 安装通过证明开发安装链；并不等于已在干净环境用 wheel 部署成云端服务。发布前应在另一新环境安装构建产物、执行 smoke test，并保存环境快照。

## 文档回归保护

文档链接测试检查相对文件是否存在，不联网检查外部站点，也不完整模拟 Markdown 渲染器的锚点规则。Python fenced 片段做语法编译，不自动执行所有片段；真正的两份完整示例通过标记为 integration 的测试执行。

依赖一致性测试核对 requirements.txt 与 pyproject.toml 的运行约束，以及 build setuptools 与开发 pin。后续更新版本应同时改这些来源，不能只改其中一个导致安装方式不同。

## 已核验的历史基线

| 代码提交 | CI run | 范围与结果 |
|---|---|---|
| `ca56654` | [#4](https://github.com/shenjackyuanjie/weird_electron/actions/runs/38501486371) | 旧依赖，Ubuntu3.11/Windows3.13，各194 passed，0跳过，语句覆盖95.08% |
| `3ff361b` | [#5](https://github.com/shenjackyuanjie/weird_electron/actions/runs/38557194665) | 新依赖，四个环境各194 passed，0失败/错误/跳过，语句覆盖95.08%；两条SciPy批量复测结果一致 |
| `130463f` | [#6](https://github.com/shenjackyuanjie/weird_electron/actions/runs/38559204791) | 新依赖与文档示例，四个环境各228 passed，0失败/错误/跳过，语句覆盖95.08% |

上表是指定提交的记录，不是对任何未来 main 的承诺；应查看对应提交的 JUnit/Actions，不把测试总数写成永久常量。

## 本次文档与依赖交付验证（2026-10-14）

CI #6 对应完整提交 `130463fe37ab0d60731bfd52ffbefc1c62fc56cb`，状态 completed/success。已实际下载并核对四份JUnit、coverage和运行产物，结果如下：

| 环境 | 通过 | 失败/错误/跳过 | 语句覆盖率 |
|---|---:|---:|---:|
| Ubuntu / Python3.11 | 228 | 0/0/0 | 95.08%（676/711） |
| Ubuntu / Python3.12 | 228 | 0/0/0 | 95.08%（676/711） |
| Ubuntu / Python3.13 | 228 | 0/0/0 | 95.08%（676/711） |
| Windows / Python3.13 | 228 | 0/0/0 | 95.08%（676/711） |

新增34项文档相关检查，包括两种策略运行完整local_loop和一次manual_dispatch手工JSON链的真实AC集成测试。每个环境还完成独立A/B/C六区间Demo、pip check、Ruff、七类Schema导出和wheel构建。

Ubuntu3.11与3.13各完成40 seed×两策略实验：每条80个episode，78完成，2个seed=6事故A的供电不足案例明确返回NO_FEASIBLE_DISPATCH。每条314个已执行区间均保留实际receipt.validation且execution_audit.passed=true；operational_errors与executed_constraint_violations均为0。未完成样本的完整周期比率保持null，不编造停机后的能量。

原始Artifacts：Ubuntu3.11为11891512742，Ubuntu3.12为11890743062，Ubuntu3.13为11891597684，Windows3.13为11891128122，均属于上述CI #6。第三方固定版本与仍受上游限制的包详见[依赖说明](dependencies.md)。

本节是验证完成后的文档补记，不改变已测代码、依赖或测试。性能和随机案例统计采用特定仿真条件，不能当真实系统SLA或全部物理状态的安全证明。原计划最后需要的Agent/云端指标仍见[交接清单](handoff.md)。
