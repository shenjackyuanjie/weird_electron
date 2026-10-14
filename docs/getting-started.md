# 安装、运行与 CLI

[文档首页](README.md) · [排错](troubleshooting.md) · [依赖](dependencies.md)

## 环境与安装方式

支持 CPython 3.11、3.12、3.13。CI 覆盖 Ubuntu 三个版本和 Windows 3.13；macOS 没有在本轮 CI 验证。`requires-python` 仍为 `>=3.11,<3.14`，不要使用 `--ignore-requires-python` 强行安装其他解释器。

### Windows PowerShell：不需要修改脚本执行策略

```powershell
git clone https://github.com/shenjackyuanjie/weird_electron.git
cd weird_electron
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest --require-ac
.\.venv\Scripts\python.exe -m simulator demo --scenario A --output outputs/demo-A
```

没有 `py` 启动器时，先用 `python --version` 确认版本，再以 `python -m venv .venv` 创建环境。下面命令默认使用已激活的虚拟环境；也可始终使用上述完整 Python 路径。

### Linux

```bash
git clone https://github.com/shenjackyuanjie/weird_electron.git
cd weird_electron
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
python -m pip check
python -m pytest --require-ac
```

使用已安装的 3.11/3.12 时替换解释器名。缺少 `venv` 模块要安装对应解释器的 venv 组件；不要改用全局 `sudo pip`。

### 只运行与开发安装的区别

`python -m pip install .` 安装运行依赖和命令行入口，不安装 pytest/Ruff。开发者用 `requirements-dev.txt` 加 editable 安装。`requirements.txt` 与 `pyproject.toml` 运行依赖保持一致；`--no-deps -e .` 的前提是已经安装 requirements，不能把 `--no-deps` 当作绕开版本冲突的办法。

不进行 editable 安装也可以在仓库根目录执行 `python -m simulator`。`python -m examples.local_loop` 等示例属于源仓库，不打包进运行 wheel。

### 更新已有环境

```bash
git switch main
git pull --ff-only origin main
python -m pip install --upgrade --upgrade-strategy eager -r requirements-dev.txt
python -m pip install --no-deps -e .
python -m pip check
python -m pytest --require-ac
```

依赖栈跨度较大或环境已混装时，优先新建另一个虚拟环境；不要在带未备份数据的目录执行删除命令。pip 的 eager 更新仍遵守所有上游限制，并不保证每个传递依赖都是全局最新版。

## Demo 命令

```bash
python -m simulator --help
python -m simulator demo --help
python -m simulator demo --scenario A --output outputs/demo-A
python -m simulator demo --scenario B --output outputs/demo-B
python -m simulator demo --scenario C --output outputs/demo-C
python -m simulator demo --scenario A --policy baseline --steps 6 --output outputs/baseline-A
```

| 参数 | 默认值 | 含义 |
|---|---|---|
| `--scenario` | `A` | `A/B/C`，见[场景](scenarios.md) |
| `--policy` | `optimizer` | `optimizer` 或 `baseline` |
| `--steps` | `6` | 总区间数，至少 3；不是秒数 |
| `--config` | 内置 `MicrogridConfig` | UTF-8 JSON 配置文件 |
| `--output` | `outputs/demo` | 输出目录；同名文件会覆盖 |

默认每区间 5 秒。第一个区间正常，第二个区间前注入事故，最后一个区间前恢复正常参数。六步合计 30 秒仿真时间，不是 30 秒实时播放。

成功返回 `complete=true` 和退出码 0；未完成返回 2，并保留已有证据。初始状态还没有潮流结果，PCC 电压/主网功率可能为 `null`，不能显示为“已正常运行”。

## 配置

```bash
python -m simulator demo --scenario A --config examples/demo-config.json --output outputs/custom-A
```

配置是 `MicrogridConfig`，不是 state 或 plan。支持缺省字段；**未知字段会拒绝**。单位 kW、kWh、秒、SOC 0–1，`step_seconds` 必须是数值。完整默认值和限制见[模型](model.md)。

例如下列文件改变负荷和电池配置，其余使用默认值：

```json
{
  "step_seconds": 5,
  "load_critical_kw": 180,
  "load_normal_kw": 250,
  "battery": {
    "capacity_kwh": 500,
    "initial_soc": 0.65,
    "soc_min": 0.1,
    "soc_max": 0.9
  }
}
```

降低电池容量或 PCC 上限可能使事故无法恢复；这不一定是程序错误。默认参数并非真实设备规范。

## 批量实验与 Schema

```bash
python -m simulator batch --cases 40 --steps 4 --output outputs/batch
python -m simulator schemas --output outputs/schemas
```

`batch` 的 `cases` 范围为 1–10000，每个 seed 运行两种策略；40 cases 是 80 episodes。CLI 没有 `--seed`、`--severity` 或 `batch --config`，定制这些行为需使用[Python API](api.md)。不要传入不存在的参数。

`schemas` 导出七个顶层 JSON Schema，详见[协议](contracts.md)。

## 读取结果

Demo 目录有 `config.json`、`summary.json`、`trace.jsonl`。批量目录还包含 `results.csv`、汇总 `summary.json` 和每个 `seed-NNN-policy/` 子目录。

```bash
python -m json.tool outputs/demo-A/summary.json
```

JSONL 每一行是完整的一次控制调用，包括候选、拒绝原因和执行回执；不要把整个 JSONL 当成一个 JSON 对象解析。指标含义见[实验与指标](experiments.md)。

运行前后保存 `git rev-parse HEAD` 和 `python -m pip freeze`，与输出放在一起。不要提交 `.venv`、凭据或无关的设备数据。
