"""Independent hard-rule + AC gate; never trusts optimizer's grid estimate."""
from power_engine.battery import project_soc
from power_engine.contracts import (
    DispatchPlan, MicrogridConfig, MicrogridState, RuleViolation,
    ValidationResult, checked, fingerprint,
)
from power_engine.power_flow import run_power_flow

POWER_TOL_KW = 0.02  # Numerical tolerance, not an operating reserve.
SOC_TOL = 1e-10


def validate_plan(state, plan, config: MicrogridConfig | None = None) -> ValidationResult:
    state = checked(MicrogridState, state)
    plan = checked(DispatchPlan, plan)
    cfg = checked(MicrogridConfig, config or MicrogridConfig())
    violations = []

    def reject(code, message, actual=None, limit=None):
        violations.append(RuleViolation(code=code, message=message, actual=actual, limit=limit))

    if plan.state_fingerprint != fingerprint(state):
        reject("STALE_STATE", "Plan does not refer to the exact current state")
    if not state.grid_available:
        reject("UNSUPPORTED_ISLAND_MODE", "Grid-forming/islanding is not modelled")
    if not cfg.battery.soc_min - SOC_TOL <= state.battery_soc <= cfg.battery.soc_max + SOC_TOL:
        reject("CURRENT_SOC_LIMIT", "Current SOC is outside operating bounds", state.battery_soc)
    if plan.critical_shed_kw != 0:
        reject("CRITICAL_LOAD_SHED", "Critical load shedding is forbidden", plan.critical_shed_kw, 0)
    if plan.normal_shed_kw > state.normal_shed_max_kw:
        reject("NORMAL_SHED_LIMIT", "Normal shedding exceeds permitted amount",
               plan.normal_shed_kw, state.normal_shed_max_kw)
    if plan.pv_power_kw > state.pv_available_kw:
        reject("PV_AVAILABILITY", "PV exceeds available power", plan.pv_power_kw, state.pv_available_kw)
    dis_max = min(state.battery_discharge_max_kw, cfg.battery.discharge_max_kw)
    ch_max = min(state.battery_charge_max_kw, cfg.battery.charge_max_kw)
    if plan.battery_power_kw > dis_max + 1e-8:
        reject("ESS_DISCHARGE_LIMIT", "Discharge exceeds current/nameplate limit", plan.battery_power_kw, dis_max)
    if -plan.battery_power_kw > ch_max + 1e-8:
        reject("ESS_CHARGE_LIMIT", "Charge exceeds current/nameplate limit", -plan.battery_power_kw, ch_max)
    soc = project_soc(state.battery_soc, plan.battery_power_kw, plan.duration_seconds, cfg.battery)
    if soc < cfg.battery.soc_min - SOC_TOL:
        reject("SOC_MIN", "Plan would deplete SOC below minimum", soc, cfg.battery.soc_min)
    if soc > cfg.battery.soc_max + SOC_TOL:
        reject("SOC_MAX", "Plan would charge above maximum SOC", soc, cfg.battery.soc_max)
    flow = None
    if not violations:
        flow = run_power_flow(state, plan, cfg)
        if not flow.converged:
            reject(flow.error_code or "POWER_FLOW_FAILED", flow.message or "No usable AC result")
        else:
            if flow.grid_power_kw > state.grid_import_max_kw + POWER_TOL_KW:
                reject("GRID_IMPORT_LIMIT", "Actual upstream import exceeds PCC limit",
                       flow.grid_power_kw, state.grid_import_max_kw)
            if flow.grid_power_kw < -state.grid_export_max_kw - POWER_TOL_KW:
                reject("GRID_EXPORT_LIMIT", "Actual export exceeds PCC limit",
                       -flow.grid_power_kw, state.grid_export_max_kw)
            if flow.min_voltage_pu < cfg.network.voltage_min_pu:
                reject("VOLTAGE_LOW", "AC bus voltage below minimum", flow.min_voltage_pu, cfg.network.voltage_min_pu)
            if flow.max_voltage_pu > cfg.network.voltage_max_pu:
                reject("VOLTAGE_HIGH", "AC bus voltage above maximum", flow.max_voltage_pu, cfg.network.voltage_max_pu)
            if flow.line_loading_percent > cfg.network.loading_max_percent:
                reject("LINE_OVERLOAD", "Feeder thermal limit exceeded",
                       flow.line_loading_percent, cfg.network.loading_max_percent)
            if abs(flow.balance_residual_kw) > POWER_TOL_KW:
                reject("POWER_BALANCE", "AC energy balance residual is too large", flow.balance_residual_kw, POWER_TOL_KW)
    return ValidationResult(request_id=plan.request_id, plan_id=plan.plan_id, passed=not violations,
                            state_fingerprint=fingerprint(state), plan_fingerprint=fingerprint(plan),
                            config_fingerprint=fingerprint(cfg), violated_rules=tuple(violations),
                            predicted_soc=soc, power_flow=flow)
