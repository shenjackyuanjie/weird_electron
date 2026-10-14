"""Post-execution audit; uses observed state and the gate saved in the actual receipt.

This is separate from candidate rejection counts. It never estimates energy after
an episode stops and never substitutes a candidate's approval for execution evidence.
"""
import math

from power_engine.battery import SOC_TOL, project_soc, soc_within_limits
from power_engine.contracts import (
    DispatchPlan, ExecutionReceipt, MicrogridConfig, MicrogridState, checked, fingerprint,
)
from power_engine.validator import POWER_TOL_KW

SETPOINT_TOL_KW = 1e-8


def audit_execution(before, after, plan, receipt, config) -> dict:
    codes = []

    def require(condition, code):
        if not condition and code not in codes:
            codes.append(code)

    try:
        before = checked(MicrogridState, before)
        after = checked(MicrogridState, after)
        plan = checked(DispatchPlan, plan)
        receipt = checked(ExecutionReceipt, receipt)
        cfg = checked(MicrogridConfig, config)
    except (ValueError, TypeError):
        return {"passed": False, "violated_rules": ["INVALID_EXECUTION_EVIDENCE"]}

    def close(a, b, tol=SETPOINT_TOL_KW):
        return a is not None and b is not None and math.isclose(a, b, rel_tol=0, abs_tol=tol)

    duration = (after.timestamp - before.timestamp).total_seconds()
    require(close(duration, plan.duration_seconds, 1e-6), "EXECUTION_DURATION")
    require(after.run_id == before.run_id and after.state_revision == before.state_revision + 1,
            "EXECUTION_STATE_SEQUENCE")
    require(plan.state_fingerprint == fingerprint(before), "STALE_STATE")
    require(receipt.status == "applied" and receipt.plan_id == plan.plan_id
            and receipt.request_id == plan.request_id and receipt.timestamp == after.timestamp
            and receipt.state_revision == after.state_revision
            and receipt.plan_fingerprint == fingerprint(plan), "RECEIPT_BINDING")
    require(soc_within_limits(after.battery_soc, cfg.battery), "EXECUTED_SOC_LIMIT")
    predicted = project_soc(before.battery_soc, after.battery_power_kw, plan.duration_seconds, cfg.battery)
    require(close(after.battery_soc, predicted, SOC_TOL), "EXECUTED_SOC_ENERGY")
    require(after.battery_power_kw <= min(before.battery_discharge_max_kw,
                                         cfg.battery.discharge_max_kw) + SETPOINT_TOL_KW,
            "ESS_DISCHARGE_LIMIT")
    require(-after.battery_power_kw <= min(before.battery_charge_max_kw,
                                          cfg.battery.charge_max_kw) + SETPOINT_TOL_KW,
            "ESS_CHARGE_LIMIT")
    require(after.pv_power_kw <= before.pv_available_kw + SETPOINT_TOL_KW, "PV_AVAILABILITY")
    require(close(after.critical_served_kw, before.load_critical_kw), "CRITICAL_LOAD_SHED")
    require(before.load_normal_kw - before.normal_shed_max_kw - SETPOINT_TOL_KW
            <= after.normal_served_kw <= before.load_normal_kw + SETPOINT_TOL_KW, "NORMAL_SHED_LIMIT")
    require(close(after.battery_power_kw, plan.battery_power_kw)
            and close(after.pv_power_kw, plan.pv_power_kw)
            and close(after.normal_served_kw, before.load_normal_kw - plan.normal_shed_kw),
            "EXECUTED_SETPOINT_MISMATCH")
    grid = after.grid_power_kw
    voltage = after.pcc_voltage_pu
    require(grid is not None and grid <= before.grid_import_max_kw + POWER_TOL_KW, "GRID_IMPORT_LIMIT")
    require(grid is not None and grid >= -before.grid_export_max_kw - POWER_TOL_KW, "GRID_EXPORT_LIMIT")
    require(voltage is not None and voltage >= cfg.network.voltage_min_pu, "VOLTAGE_LOW")
    require(voltage is not None and voltage <= cfg.network.voltage_max_pu, "VOLTAGE_HIGH")

    validation = receipt.validation
    if validation is None:
        require(False, "MISSING_EXECUTION_VALIDATION")
    else:
        require(validation.passed and not validation.violated_rules, "EXECUTED_REJECTED_PLAN")
        require(validation.state_fingerprint == fingerprint(before)
                and validation.plan_fingerprint == fingerprint(plan)
                and validation.config_fingerprint == fingerprint(cfg)
                and validation.request_id == plan.request_id and validation.plan_id == plan.plan_id,
                "EXECUTION_VALIDATION_BINDING")
        require(close(validation.predicted_soc, after.battery_soc, SOC_TOL), "PREDICTED_SOC_MISMATCH")
        flow = validation.power_flow
        if flow is None or not flow.converged:
            require(False, "MISSING_EXECUTION_POWER_FLOW")
        else:
            require(close(flow.pcc_voltage_pu, voltage) and close(flow.grid_power_kw, grid),
                    "EXECUTED_POWER_FLOW_MISMATCH")
            require(flow.min_voltage_pu >= cfg.network.voltage_min_pu, "VOLTAGE_LOW")
            require(flow.max_voltage_pu <= cfg.network.voltage_max_pu, "VOLTAGE_HIGH")
            require(flow.line_loading_percent <= cfg.network.loading_max_percent, "LINE_OVERLOAD")
            require(abs(flow.balance_residual_kw) <= POWER_TOL_KW, "POWER_BALANCE")
            residual = None if grid is None else (
                grid + after.pv_power_kw + after.battery_power_kw
                - after.critical_served_kw - after.normal_served_kw - flow.loss_kw
            )
            require(residual is not None and abs(residual) <= POWER_TOL_KW, "EXECUTED_POWER_BALANCE")
    return {"passed": not codes, "violated_rules": codes}
