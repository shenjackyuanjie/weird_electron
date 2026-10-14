import json

import pytest
from pydantic import ValidationError

from power_engine.api import invoke
from power_engine.contracts import DispatchPlan, MicrogridState, fingerprint
from power_engine.optimizer import optimize_dispatch
from power_engine.validator import validate_plan
from simulator.scenarios import scenario_state


def plan_for(state, **updates):
    return DispatchPlan(state_fingerprint=fingerprint(state), pv_power_kw=state.pv_available_kw,
                        battery_power_kw=0).model_copy(update=updates)


@pytest.mark.parametrize("field,value,code", [
    ("battery_power_kw", 201, "ESS_DISCHARGE_LIMIT"),
    ("battery_power_kw", -151, "ESS_CHARGE_LIMIT"),
    ("pv_power_kw", 351, "PV_AVAILABILITY"),
    ("critical_shed_kw", 0.001, "CRITICAL_LOAD_SHED"),
    ("normal_shed_kw", 301, "NORMAL_SHED_LIMIT"),
    ("state_fingerprint", "0" * 64, "STALE_STATE"),
])
def test_unsafe_rules_without_solver(state, config, field, value, code, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Bad hard rules must be rejected before running AC")
    monkeypatch.setattr("power_engine.validator.run_power_flow", forbidden)
    result = validate_plan(state, plan_for(state, **{field: value}), config)
    assert not result.passed
    assert code in {r.code for r in result.violated_rules}
    assert "pass" in result.wire() and "passed" not in result.wire()


@pytest.mark.parametrize("soc,power,code", [(0.10001, 200, "SOC_MIN"), (0.89999, -150, "SOC_MAX")])
def test_future_soc(state, config, soc, power, code):
    state = state.model_copy(update={"battery_soc": soc})
    result = validate_plan(state, plan_for(state, battery_power_kw=power, duration_seconds=300), config)
    assert code in {r.code for r in result.violated_rules}


def test_current_soc_invalid(state, config):
    state = state.model_copy(update={"battery_soc": 0.05})
    result = validate_plan(state, plan_for(state), config)
    assert "CURRENT_SOC_LIMIT" in {r.code for r in result.violated_rules}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_plan_rejected_even_model_copy(state, value):
    with pytest.raises(ValidationError):
        validate_plan(state, plan_for(state, battery_power_kw=value))


def test_extra_fields_rejected(state):
    with pytest.raises(ValidationError):
        MicrogridState.model_validate({**state.wire(), "soc_percent": 60})


def test_scenario_preserves_soc_and_recovers(state, config):
    fault = scenario_state(state, config, "C")
    assert fault.alarm_code == "ESS_DERATED"
    assert fault.battery_discharge_max_kw == 20
    recovered = scenario_state(fault, config, "normal")
    assert recovered.battery_soc == state.battery_soc
    assert recovered.alarm_code is None
    assert recovered.battery_discharge_max_kw == config.battery.discharge_max_kw


def test_api_errors_are_structured(state):
    result = invoke("validate_plan", {"state": state.wire(), "request_id": "r1"})
    assert not result["ok"] and result["error_code"] == "INVALID_INPUT"
    assert result["request_id"] == "r1"
    json.dumps(result, allow_nan=False)


def test_api_optimization(state):
    result = invoke("optimize_dispatch", {"state": state.wire()})
    assert result["ok"] and result["result"]["plan"] is not None


def test_stale_feedback(state, config):
    bad = validate_plan(state, plan_for(state, battery_power_kw=201), config)
    next_state = state.model_copy(update={"state_revision": 1})
    with pytest.raises(RuntimeError, match="different state"):
        optimize_dispatch(next_state, config, feedback=bad)


@pytest.mark.parametrize("severity", [-1, float("nan"), float("inf")])
def test_invalid_scenario_severity(state, config, severity):
    with pytest.raises(ValueError):
        scenario_state(state, config, "A", severity)


def test_api_request_id_propagates(state):
    result = invoke("optimize_dispatch", {"state": state.wire(), "request_id": "trace-123"})
    assert result["result"]["plan"]["request_id"] == "trace-123"


def test_islanding_validator_fails_closed(state, config):
    state = state.model_copy(update={"grid_available": False})
    result = validate_plan(state, plan_for(state), config)
    assert not result.passed
    assert "UNSUPPORTED_ISLAND_MODE" in {r.code for r in result.violated_rules}
