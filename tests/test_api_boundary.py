"""Decoded JSON boundary and request correlation regressions (no AC dependency)."""
import json

import pytest
from pydantic import ValidationError

from power_engine.api import invoke
from power_engine.baseline import fixed_rule_dispatch
from power_engine.contracts import DispatchPlan, fingerprint
from power_engine.optimizer import optimize_dispatch


@pytest.mark.parametrize("duration", ["5", [], {}, True, False, 0, -1, 301, float("nan"), float("inf")])
def test_bad_duration_is_invalid_input(state, duration):
    result = invoke("optimize_dispatch", {
        "state": state.wire(), "duration_seconds": duration, "request_id": "bad-duration",
    })
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_INPUT"
    assert result["request_id"] == "bad-duration"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("policy", [optimize_dispatch, fixed_rule_dispatch])
@pytest.mark.parametrize("duration", ["5", [], {}, True])
def test_direct_policies_reject_bad_duration_consistently(state, config, policy, duration):
    with pytest.raises(ValueError):
        policy(state, config, duration_seconds=duration)


@pytest.mark.parametrize("request_id", [None, 42, False, [], {}, "", "  ", "x" * 129])
def test_bad_request_id_is_not_stringified(state, request_id):
    result = invoke("optimize_dispatch", {"state": state.wire(), "request_id": request_id})
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_INPUT"
    assert isinstance(result["request_id"], str) and result["request_id"].strip()


def test_validation_inherits_plan_request_id(state):
    plan = DispatchPlan(state_fingerprint=fingerprint(state), request_id="same-trace",
                        pv_power_kw=350, battery_power_kw=201)
    response = invoke("validate_plan", {"state": state.wire(), "plan": plan.wire()})
    assert response["ok"]
    assert response["request_id"] == response["result"]["request_id"] == "same-trace"


@pytest.mark.parametrize("tool", ["run_power_flow", "validate_plan"])
def test_conflicting_request_ids_are_rejected_before_calculation(state, monkeypatch, tool):
    plan = DispatchPlan(state_fingerprint=fingerprint(state), request_id="plan-trace",
                        pv_power_kw=350, battery_power_kw=201)
    def forbidden(*args, **kwargs):
        raise AssertionError("Mismatched trace must be rejected before computation")
    monkeypatch.setattr(f"power_engine.api.{tool}", forbidden)
    response = invoke(tool, {"state": state.wire(), "plan": plan.wire(), "request_id": "other-trace"})
    assert not response["ok"] and response["error_code"] == "INVALID_INPUT"


def test_unknown_tool_has_dedicated_error():
    response = invoke("missing-tool", {"request_id": "unknown"})
    assert response["error_code"] == "UNKNOWN_TOOL"
    assert response["request_id"] == "unknown"


@pytest.mark.parametrize("duration", [5, 5.0, None])
def test_valid_durations_still_work(state, duration):
    response = invoke("optimize_dispatch", {"state": state.wire(), "duration_seconds": duration})
    assert response["ok"]
    assert response["result"]["plan"]["duration_seconds"] == 5


def test_plan_schema_rejects_boolean_duration(state):
    with pytest.raises(ValidationError):
        DispatchPlan(state_fingerprint=fingerprint(state), pv_power_kw=0,
                     battery_power_kw=0, duration_seconds=True)
