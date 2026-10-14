"""Real balanced AC power flow. No synthetic fallback or implicit island slack."""
import math

from power_engine.contracts import (
    DispatchPlan, MicrogridConfig, MicrogridState, PowerFlowResult, checked,
)


def run_power_flow(state, plan, config: MicrogridConfig | None = None) -> PowerFlowResult:
    state = checked(MicrogridState, state)
    plan = checked(DispatchPlan, plan)
    cfg = checked(MicrogridConfig, config or MicrogridConfig())
    if not state.grid_available:
        return PowerFlowResult(converged=False, error_code="UNSUPPORTED_ISLAND_MODE",
                               message="No grid-forming inverter model is implemented; fail closed.")
    if plan.normal_shed_kw > state.load_normal_kw or plan.critical_shed_kw > state.load_critical_kw:
        return PowerFlowResult(converged=False, error_code="INVALID_LOAD", message="Shedding exceeds demand")
    try:
        import pandapower as pp
    except ImportError as exc:
        return PowerFlowResult(converged=False, error_code="DEPENDENCY_UNAVAILABLE", message=str(exc))
    try:
        n = cfg.network
        net = pp.create_empty_network(sn_mva=1, f_hz=cfg.nominal_frequency_hz)
        upstream = pp.create_bus(net, vn_kv=n.nominal_kv, name="upstream")
        pcc = pp.create_bus(net, vn_kv=n.nominal_kv, name="microgrid_pcc")
        pp.create_ext_grid(net, upstream, vm_pu=state.grid_voltage_pu)
        pp.create_line_from_parameters(net, upstream, pcc, length_km=n.length_km,
                                      r_ohm_per_km=n.r_ohm_per_km, x_ohm_per_km=n.x_ohm_per_km,
                                      c_nf_per_km=0, max_i_ka=n.max_current_ka)
        pp.create_sgen(net, pcc, p_mw=plan.pv_power_kw / 1000, q_mvar=0, name="pv")
        # pandapower uses the consumer sign: charging positive.
        pp.create_storage(net, pcc, p_mw=-plan.battery_power_kw / 1000,
                          max_e_mwh=cfg.battery.capacity_kwh / 1000,
                          soc_percent=state.battery_soc * 100, name="ess")
        q_factor = math.tan(math.acos(n.load_power_factor))
        critical = state.load_critical_kw - plan.critical_shed_kw
        normal = state.load_normal_kw - plan.normal_shed_kw
        for name, kw in (("critical_load", critical), ("normal_load", normal)):
            pp.create_load(net, pcc, p_mw=kw / 1000, q_mvar=kw * q_factor / 1000, name=name)
        pp.runpp(net, algorithm="nr", numba=False, init="flat", max_iteration=30,
                 tolerance_mva=1e-9, check_connectivity=True)
        voltages = net.res_bus.vm_pu.to_numpy()
        grid_kw = float(net.res_ext_grid.p_mw.sum() * 1000)
        losses = float(net.res_line.pl_mw.sum() * 1000)
        loading = float(net.res_line.loading_percent.max())
        values = [*voltages, grid_kw, losses, loading]
        if not net.converged or not all(math.isfinite(float(v)) for v in values):
            raise ValueError("Non-converged or non-finite AC result")
        residual = grid_kw + plan.pv_power_kw + plan.battery_power_kw - critical - normal - losses
        return PowerFlowResult(converged=True, pcc_voltage_pu=float(voltages[pcc]),
                               min_voltage_pu=float(min(voltages)), max_voltage_pu=float(max(voltages)),
                               line_loading_percent=loading, grid_power_kw=grid_kw,
                               loss_kw=max(0, losses), balance_residual_kw=residual)
    except Exception as exc:
        # Solver failures are data, not safe operating points. No NaN can escape the schema.
        return PowerFlowResult(converged=False, error_code="POWER_FLOW_FAILED",
                               message=f"{type(exc).__name__}: {exc}")
