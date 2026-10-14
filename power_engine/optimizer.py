"""Single-period LP, with explicit charge/discharge mode enumeration (no simultaneous cycling)."""
import math

from scipy.optimize import linprog

from power_engine.battery import power_limits, soc_within_limits
from power_engine.contracts import (
    DURATION_ADAPTER, DispatchPlan, EngineError, MicrogridConfig, MicrogridState,
    OptimizationResult, ValidationResult, checked, fingerprint,
)


def planning_inputs(state, cfg, duration_seconds, feedback):
    duration_seconds = DURATION_ADAPTER.validate_python(duration_seconds)
    if not math.isfinite(duration_seconds) or not 0 < duration_seconds <= 300:
        raise ValueError("duration_seconds must be finite and in (0, 300]")
    reserve = 0.0
    grid_cap = state.grid_import_max_kw
    if feedback is not None:
        feedback = checked(ValidationResult, feedback)
        if feedback.state_fingerprint != fingerprint(state) or feedback.config_fingerprint != fingerprint(cfg):
            raise EngineError("STALE_FEEDBACK", "Feedback belongs to a different state or configuration")
        codes = {r.code for r in feedback.violated_rules}
        if feedback.power_flow and feedback.power_flow.converged:
            loss = feedback.power_flow.loss_kw or 0
            reserve = loss
            if "GRID_IMPORT_LIMIT" in codes:
                reserve = loss * 1.10 + 0.02  # Conservative receiving-load reduction on import retry.
            if codes & {"VOLTAGE_LOW", "LINE_OVERLOAD"}:
                grid_cap *= 0.7  # Heuristic only; independent AC gate may still refuse.
    charge, discharge = power_limits(state, cfg.battery, duration_seconds)
    return reserve, grid_cap, charge, discharge


def optimize_dispatch(state, config: MicrogridConfig | None = None, *, duration_seconds=None,
                      feedback=None) -> OptimizationResult:
    state = checked(MicrogridState, state)
    cfg = checked(MicrogridConfig, config or MicrogridConfig())
    duration = DURATION_ADAPTER.validate_python(
        cfg.step_seconds if duration_seconds is None else duration_seconds
    )
    if not state.grid_available:
        return OptimizationResult(status="error", error_code="UNSUPPORTED_ISLAND_MODE")
    if not soc_within_limits(state.battery_soc, cfg.battery):
        return OptimizationResult(status="error", error_code="CURRENT_SOC_LIMIT")
    reserve, grid_cap, charge, discharge = planning_inputs(state, cfg, duration, feedback)
    # Variables: import, export, charge, discharge, used PV, shed normal load (all kW).
    costs = [cfg.import_cost_per_kwh, 0, cfg.battery_cost_per_kwh,
             cfg.battery_cost_per_kwh, -cfg.curtail_cost_per_kwh, cfg.shed_cost_per_kwh]
    demand = state.load_critical_kw + state.load_normal_kw
    solutions = []
    for mode in ("discharge", "charge"):
        bounds = [(0, grid_cap), (0, state.grid_export_max_kw),
                  (0, charge if mode == "charge" else 0),
                  (0, discharge if mode == "discharge" else 0),
                  (0, state.pv_available_kw), (0, state.normal_shed_max_kw)]
        result = linprog(costs, A_eq=[[1, -1, -1, 1, 1, 1]], b_eq=[demand + reserve],
                         bounds=bounds, method="highs", options={"time_limit": 5.0})
        if result.success:
            solutions.append(result)
        elif result.status != 2:
            return OptimizationResult(status="error", error_code="OPTIMIZER_FAILED", message=result.message)
    if not solutions:
        return OptimizationResult(status="infeasible", error_code="NO_FEASIBLE_DISPATCH",
                                  message="Available supply cannot serve protected demand under current constraints")
    best = min(solutions, key=lambda item: item.fun)
    grid_in, grid_out, ch, dis, pv, shed = (float(x) for x in best.x)
    plan = DispatchPlan(state_fingerprint=fingerprint(state), duration_seconds=duration,
                        pv_power_kw=max(0, pv), battery_power_kw=dis - ch,
                        normal_shed_kw=max(0, shed), expected_grid_kw=grid_in - grid_out)
    cost = (best.fun + cfg.curtail_cost_per_kwh * state.pv_available_kw) * duration / 3600
    return OptimizationResult(status="optimal", plan=plan, objective=float(cost))
