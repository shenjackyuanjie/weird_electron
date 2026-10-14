# 依赖版本、兼容限制与升级记录

[文档首页](README.md) · [安装与升级](getting-started.md) · [测试流程](testing.md)

**核验日期：2026-10-14。** 依据 PyPI 发布元数据和官方 GitHub Releases 核验稳定、未撤回的发行版，再以实际 pip 解析、pip check、真实潮流测试和实验验证组合。不是把所有版本号盲目改成最大值，也不是安全漏洞审计。

## 直接依赖

| 包 | 升级前 | 本次固定版本 | 选择依据 |
|---|---|---|---|
| pandapower | 3.4.0 | **3.5.6** | 核验时最新稳定版 |
| numpy | 2.3.5 | **2.4.6** | 最新全局版2.5.4，但pandapower3.5.6要求 `numpy>=1.26,<2.5`；选择约束内最新版 |
| scipy（Python3.11） | 1.16.3 | **1.17.1** | 最新支持3.11的分支；用环境marker选择 |
| scipy（Python3.12/3.13） | 1.16.3 | **1.18.1** | 最新稳定版要求Python>=3.12 |
| pydantic | 2.12.5 | **2.14.1** | 核验时最新稳定版 |
| pytest | 9.0.2 | **9.1.1** | 核验时最新稳定版 |
| pytest-cov | 7.0.0 | **7.1.0** | 核验时最新稳定版 |
| ruff | 0.14.14 | **0.17.0** | 核验时最新稳定版 |
| setuptools | 构建要求>=75，未固定 | **84.0.0** | 固定本次核验的最新构建工具；开发与构建声明一致 |

没有为追求单一版本而删除原有Python3.11支持。项目范围仍为 `>=3.11,<3.14`。NumPy2.4.6仍支持3.11；SciPy按解释器条件分别固定。新环境可选3.13，旧3.11用户不用强制迁移。

`requirements.txt` 与 `pyproject.toml` 同时声明运行依赖；`requirements-dev.txt` 包含运行依赖和测试/lint/构建工具。测试检查这些声明一致，避免安装方式不同却得到不同的直接约束。

## CI Actions

| Action | 原版本 | 本次固定tag |
|---|---|---|
| actions/checkout | v4 | **v7.0.1** |
| actions/setup-python | v5 | **v7.0.0** |
| actions/upload-artifact | v4 | **v7.0.2** |

使用核验的具体release tag，而不是只写移动的major tag。它们不是完整commit SHA固定；本次不把tag pin说成供应链完整性保证。新Action已经由本仓库实际CI执行。

## 传递依赖与未强制升级的包

安装使用 `--upgrade --upgrade-strategy eager`，由pip在完整依赖图内选版本，并运行pip check。本次环境例如得到 pandas2.3.3、networkx3.7、pandera0.34.1、deepdiff9.1.0、coverage7.16.2；完整清单以各环境 `requirements-resolved.txt` 为准。

CI的 `outputs/outdated.json` 仍列出以下包，这是需要说明的兼容限制：

| 包 | 已解析 | 索引较新版本 | 为什么保留 |
|---|---|---|---|
| numpy（3.12/3.13环境） | 2.4.6 | 2.5.4 | pandapower要求<2.5；3.11环境索引也受Requires-Python过滤 |
| pandas | 2.3.3 | 3.0.6 | pandapower要求 `pandas~=2.3`，即2.x兼容范围 |
| cachebox | 5.2.3 | 6.2.8 | 已解析的DeepDiff9.1.0要求 `cachebox>=5.2,<6` |

不能用 `--no-deps` 安装这些不兼容版本后宣称“已全部最新”，也不应擅自修改第三方包元数据。只有上游放宽约束并经回归后再考虑下一次升级。

pip的outdated输出与解释器有关：Python3.11环境不一定显示仅支持3.12的最新版，因此核验“全局最新”和“本环境最新可用”必须分开。该命令不判断所有业务兼容性，也不是漏洞扫描。

## 固定程度与可复现性

当前固定**直接依赖和setuptools构建工具**，尚未提交所有传递依赖的跨平台带哈希锁文件。freeze是本次解析环境的快照，不等同于长期完整供应链锁；其中editable仓库行也不能直接当离线部署包。

CI保存JUnit、coverage、配置、场景日志、解析后的完整环境、outdated报告及构建wheel。比较实验要同时固定代码SHA、Python版本和环境快照。长期部署需进一步制定全量锁定/镜像与制品留存方案，而不是只拷贝一份requirements文本就称完全确定。

## 本次真实验证

依赖升级提交为 **`3ff361b1c59272cbd6e8f1bb83fec7584ebe20a5`**，对应[Power engine tests #5](https://github.com/shenjackyuanjie/weird_electron/actions/runs/38557194665)。已下载核对四份JUnit、coverage、Demo摘要、两份批量结果和完整环境。

| 环境 | SciPy | 测试 | 失败/错误/跳过 | 语句覆盖率 |
|---|---|---:|---:|---:|
| Ubuntu / Python3.11 | 1.17.1 | 194 passed | 0/0/0 | 95.08% |
| Ubuntu / Python3.12 | 1.18.1 | 194 passed | 0/0/0 | 95.08% |
| Ubuntu / Python3.13 | 1.18.1 | 194 passed | 0/0/0 | 95.08% |
| Windows / Python3.13 | 1.18.1 | 194 passed | 0/0/0 | 95.08% |

四环境均完成依赖检查、Ruff、真实AC、三个独立Demo、七类Schema与wheel构建。两条SciPy路径在Ubuntu3.11/3.13各跑40 seed×两策略：每条80个episode，78完成，2个合理无解，运行错误0、执行审计越界0。

该记录只对上述依赖升级提交负责；后续文档示例测试的增加会改变总数，必须看其新提交的CI，不能把194复制成永久事实。

## 下次升级步骤

先核验PyPI的release、yanked状态、Requires-Python和Requires-Dist，并检查Action官方release。排除预发布与撤回版本，记录不能升级的约束链。

同时修改requirements和pyproject，按Python条件使用marker；创建新环境运行eager解析、pip check、完整真实AC测试、三个Demo、配对实验、Schema导出和wheel构建。保留相同seed比较拒绝、能量和电气约束，而不只比较测试数量。更新本文件日期与证据，不覆盖历史审查正文。

```bash
python -m pip install --upgrade --upgrade-strategy eager -r requirements-dev.txt
python -m pip install --no-deps -e .
python -m pip check
python -m pip list --outdated
python -m pytest --require-ac
```

`--no-deps -e .` 只用于已经正确装好依赖后的项目安装，不可用于规避第三方依赖冲突。

## 核验来源

- [pandapower3.5.6 PyPI元数据](https://pypi.org/pypi/pandapower/3.5.6/json)
- [NumPy全部发行记录](https://pypi.org/pypi/numpy/json)；[NumPy2.4.6](https://pypi.org/project/numpy/2.4.6/)
- [SciPy1.17.1](https://pypi.org/project/scipy/1.17.1/)；[SciPy1.18.1元数据](https://pypi.org/pypi/scipy/1.18.1/json)
- [Pydantic发行元数据](https://pypi.org/pypi/pydantic/json)
- [pytest发行元数据](https://pypi.org/pypi/pytest/json)；[pytest-cov](https://pypi.org/pypi/pytest-cov/json)
- [Ruff发行元数据](https://pypi.org/pypi/ruff/json)；[setuptools](https://pypi.org/pypi/setuptools/json)
- [DeepDiff9.1.0依赖元数据](https://pypi.org/pypi/deepdiff/9.1.0/json)
- [checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1)
- [setup-python v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0)
- [upload-artifact v7.0.2](https://github.com/actions/upload-artifact/releases/tag/v7.0.2)

全局latest接口未来会变化；这里表格按上述核验日期记录，具体安装由仓库pin决定。
