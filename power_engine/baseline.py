"""Fixed-order EMS baseline. This module never invokes an optimization solver."""
from power_engine.contracts import (
    DispatchPlan, MicrogridConfig, MicrogridState, OptimizationResult, checked, fingerprint,
)
from power_engine.optimizer import planning_inputs


def fixed_rule_dispatch(state, config: MicrogridConfig | None = None, *, duration_seconds=None,
                        feedback=None) -> OptimizationResult:
    state = checked(MicrogridState, state)
    cfg = checked(MicrogridConfig, config or MicrogridConfig())
    duration = cfg.step_seconds if duration_seconds is None else duration_seconds
    if not state.grid_available:
        return OptimizationResult(status="error", error_code="UNSUPPORTED_ISLAND_MODE")
    if not cfg.battery.soc_min <= state.battery_soc <= cfg.battery.soc_max:
        return OptimizationResult(status="error", error_code="CURRENT_SOC_LIMIT")
    reserve, cap, charge_max, discharge_max = planning_inputs(state, cfg, duration, feedback)
    demand = state.load_critical_kw + state.load_normal_kw + reserve
    pv = state.pv_available_kw
    shed = battery = grid = 0.0
    if pv <= demand:
        deficit = demand - pv
        grid = min(deficit, cap)
        battery = min(deficit - grid, discharge_max)
        shed = max(0.0, deficit - grid - battery)
        if shed > state.normal_shed_max_kw + 1e-8:
            return OptimizationResult(status="infeasible", error_code="NO_FEASIBLE_DISPATCH")
    else:
        battery = -min(pv - demand, charge_max)
        export = min(pv - demand + battery, state.grid_export_max_kw)
        pv = demand - battery + export
        grid = -export
    plan = DispatchPlan(state_fingerprint=fingerprint(state), duration_seconds=duration,
                        pv_power_kw=max(0, pv), battery_power_kw=battery,
                        normal_shed_kw=min(shed, state.normal_shed_max_kw), expected_grid_kw=grid)
    return OptimizationResult(status="feasible", plan=plan,
                              message="Fixed-rule feasible candidate, not an economic optimum")
