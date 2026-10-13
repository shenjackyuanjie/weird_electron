"""Three documented fault families. Values are demo assumptions, not device specifications."""
import math

from power_engine.contracts import MicrogridConfig, MicrogridState

SCENARIOS = {"A": "光伏骤降", "B": "PCC 交换能力下降（仍然并网）", "C": "储能降额/告警"}


def initial_state(config: MicrogridConfig) -> MicrogridState:
    return MicrogridState(pv_available_kw=config.pv_available_kw, pv_power_kw=config.pv_available_kw,
                          load_critical_kw=config.load_critical_kw, load_normal_kw=config.load_normal_kw,
                          critical_served_kw=config.load_critical_kw, normal_served_kw=config.load_normal_kw,
                          normal_shed_max_kw=config.load_normal_kw, battery_soc=config.battery.initial_soc,
                          battery_charge_max_kw=config.battery.charge_max_kw,
                          battery_discharge_max_kw=config.battery.discharge_max_kw,
                          grid_import_max_kw=config.grid_import_max_kw, grid_export_max_kw=config.grid_export_max_kw,
                          grid_voltage_pu=config.grid_voltage_pu, frequency_hz=config.nominal_frequency_hz)


def scenario_state(state: MicrogridState, config: MicrogridConfig, scenario_id: str,
                   severity: float | None = None) -> MicrogridState:
    """Replace exogenous scenario settings, preserving time/SOC and invalidating old plans."""
    if scenario_id not in (*SCENARIOS, "normal"):
        raise ValueError(f"Unknown scenario_id: {scenario_id}")
    if severity is not None and (not math.isfinite(severity) or severity < 0):
        raise ValueError("severity must be finite and nonnegative")
    data = state.wire()
    data.update(scenario_id=scenario_id, state_revision=state.state_revision + 1,
                pv_available_kw=config.pv_available_kw, grid_import_max_kw=config.grid_import_max_kw,
                battery_discharge_max_kw=config.battery.discharge_max_kw, alarm_code=None,
                pcc_voltage_pu=None, grid_power_kw=None)
    if scenario_id == "A":
        data["pv_available_kw"] = min(config.pv_available_kw, 100 if severity is None else severity)
    elif scenario_id == "B":
        data["grid_import_max_kw"] = min(config.grid_import_max_kw, 40 if severity is None else severity)
    elif scenario_id == "C":
        data["battery_discharge_max_kw"] = min(config.battery.discharge_max_kw, 20 if severity is None else severity)
        data["alarm_code"] = "ESS_DERATED"
    data["pv_power_kw"] = min(state.pv_power_kw, data["pv_available_kw"])
    return MicrogridState.model_validate(data)
