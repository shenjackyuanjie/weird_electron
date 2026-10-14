"""Pure audit arithmetic with explicitly synthetic fixtures; real-AC audit is tested separately."""
from datetime import timedelta

import pytest

from power_engine.battery import project_soc
from power_engine.contracts import DispatchPlan, ExecutionReceipt, PowerFlowResult, ValidationResult, fingerprint
from simulator.metrics import audit_execution


@pytest.fixture
def evidence(state, config):
    # Lossless synthetic fixture exclusively for testing accounting/omission detection.
    plan = DispatchPlan(state_fingerprint=fingerprint(state), pv_power_kw=350, battery_power_kw=60)
    after = state.model_copy(update={
        "timestamp": state.timestamp + timedelta(seconds=5), "state_revision": 1,
        "battery_power_kw": 60, "battery_soc": project_soc(state.battery_soc, 60, 5, config.battery),
        "grid_power_kw": 90, "pcc_voltage_pu": 1,
    })
    flow = PowerFlowResult(converged=True, pcc_voltage_pu=1, min_voltage_pu=1, max_voltage_pu=1,
                           line_loading_percent=25, grid_power_kw=90, loss_kw=0, balance_residual_kw=0)
    gate = ValidationResult(request_id=plan.request_id, plan_id=plan.plan_id, passed=True,
                            state_fingerprint=fingerprint(state), plan_fingerprint=fingerprint(plan),
                            config_fingerprint=fingerprint(config), predicted_soc=after.battery_soc,
                            power_flow=flow)
    receipt = ExecutionReceipt(request_id=plan.request_id, plan_id=plan.plan_id, status="applied",
                               timestamp=after.timestamp, state_revision=1,
                               plan_fingerprint=fingerprint(plan), validation=gate)
    return state, after, plan, receipt, config


def test_valid_audit(evidence):
    assert audit_execution(*evidence) == {"passed": True, "violated_rules": []}


@pytest.mark.parametrize("change,code", [
    ({"battery_power_kw": 201}, "ESS_DISCHARGE_LIMIT"),
    ({"battery_power_kw": -151}, "ESS_CHARGE_LIMIT"),
    ({"battery_soc": 0.05}, "EXECUTED_SOC_LIMIT"),
    ({"battery_soc": 0.5}, "EXECUTED_SOC_ENERGY"),
    ({"critical_served_kw": 199}, "CRITICAL_LOAD_SHED"),
    ({"pv_power_kw": 300}, "EXECUTED_SETPOINT_MISMATCH"),
    ({"grid_power_kw": 101}, "GRID_IMPORT_LIMIT"),
    ({"grid_power_kw": -1}, "GRID_EXPORT_LIMIT"),
    ({"pcc_voltage_pu": 0.94}, "VOLTAGE_LOW"),
    ({"pcc_voltage_pu": 1.06}, "VOLTAGE_HIGH"),
    ({"grid_power_kw": None}, "GRID_IMPORT_LIMIT"),
    ({"pcc_voltage_pu": None}, "VOLTAGE_LOW"),
    ({"state_revision": 2}, "EXECUTION_STATE_SEQUENCE"),
])
def test_observed_violations_not_hidden_by_passed_candidate(evidence, change, code):
    before, after, plan, receipt, cfg = evidence
    result = audit_execution(before, after.model_copy(update=change), plan, receipt, cfg)
    assert not result["passed"] and code in result["violated_rules"]


@pytest.mark.parametrize("flow_change,code", [
    ({"line_loading_percent": 101}, "LINE_OVERLOAD"),
    ({"balance_residual_kw": 1}, "POWER_BALANCE"),
    ({"min_voltage_pu": 0.9}, "VOLTAGE_LOW"),
    ({"max_voltage_pu": 1.1}, "VOLTAGE_HIGH"),
    ({"loss_kw": 5}, "EXECUTED_POWER_BALANCE"),
])
def test_audit_reads_actual_receipt_gate(evidence, flow_change, code):
    before, after, plan, receipt, cfg = evidence
    flow = receipt.validation.power_flow.model_copy(update=flow_change)
    gate = receipt.validation.model_copy(update={"power_flow": flow})
    receipt = receipt.model_copy(update={"validation": gate})
    result = audit_execution(before, after, plan, receipt, cfg)
    assert code in result["violated_rules"]


def test_missing_gate_is_not_zero_violations(evidence):
    before, after, plan, receipt, cfg = evidence
    receipt = receipt.model_copy(update={"validation": None})
    assert "MISSING_EXECUTION_VALIDATION" in audit_execution(before, after, plan, receipt, cfg)["violated_rules"]


def test_wrong_gate_binding(evidence):
    before, after, plan, receipt, cfg = evidence
    gate = receipt.validation.model_copy(update={"config_fingerprint": "0" * 64})
    receipt = receipt.model_copy(update={"validation": gate})
    assert "EXECUTION_VALIDATION_BINDING" in audit_execution(before, after, plan, receipt, cfg)["violated_rules"]


def test_malformed_evidence_is_not_safe(evidence):
    before, after, plan, receipt, cfg = evidence
    after = after.model_copy(update={"battery_soc": float("nan")})
    assert audit_execution(before, after, plan, receipt, cfg)["violated_rules"] == ["INVALID_EXECUTION_EVIDENCE"]


def test_normal_load_allowance_and_time(evidence):
    before, after, plan, receipt, cfg = evidence
    before = before.model_copy(update={"normal_shed_max_kw": 20})
    after = after.model_copy(update={"normal_served_kw": 250, "timestamp": before.timestamp})
    codes = audit_execution(before, after, plan, receipt, cfg)["violated_rules"]
    assert "NORMAL_SHED_LIMIT" in codes and "EXECUTION_DURATION" in codes
