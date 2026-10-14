"""Regressions for PR #1's Copilot findings; AC cases use real pandapower."""
import json
from uuid import UUID

import pytest

from power_engine.api import invoke
from power_engine.baseline import fixed_rule_dispatch
from power_engine.battery import power_limits, project_soc
from power_engine.contracts import DispatchPlan, MicrogridConfig, fingerprint
from power_engine.optimizer import optimize_dispatch
from power_engine.validator import validate_plan
from simulator.controller import control_step
from simulator.simulator import MicrogridSimulator


@pytest.mark.parametrize("encoded", [
    "null", "[]", '[{"request_id": "nested"}]', '"text"', "42", "1.5", "true", "false",
])
def test_non_object_json_is_a_structured_error(encoded, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Malformed payload must not reach the optimizer")

    monkeypatch.setattr("power_engine.api.optimize_dispatch", forbidden)
    result = invoke("optimize_dispatch", json.loads(encoded))
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_INPUT"
    assert result["message"]
    assert str(UUID(result["request_id"])) == result["request_id"]
    json.dumps(result, allow_nan=False)


def test_invalid_payload_fallback_request_ids_are_distinct():
    first = invoke("validate_plan", None)
    second = invoke("run_power_flow", [])
    assert first["error_code"] == second["error_code"] == "INVALID_INPUT"
    assert first["request_id"] != second["request_id"]


@pytest.mark.parametrize("policy", [optimize_dispatch, fixed_rule_dispatch])
@pytest.mark.parametrize("boundary,direction", [("soc_min", -1), ("soc_max", 1)])
@pytest.mark.parametrize("offset", [0.0, 5e-11])
def test_policies_accept_soc_boundary_roundoff(state, config, policy, boundary, direction, offset):
    soc = getattr(config.battery, boundary) + direction * offset
    state = state.model_copy(update={"battery_soc": soc})
    before = state.wire()
    result = policy(state, config)
    assert result.plan is not None, result
    assert state.wire() == before  # No clipping or state mutation in either policy.
    charge, discharge = power_limits(state, config.battery, config.step_seconds)
    if direction < 0:
        assert discharge == 0
        assert result.plan.battery_power_kw <= 0
    else:
        assert charge == 0
        assert result.plan.battery_power_kw >= 0
    predicted = project_soc(soc, result.plan.battery_power_kw,
                            result.plan.duration_seconds, config.battery)
    assert config.battery.soc_min - 1e-10 <= predicted <= config.battery.soc_max + 1e-10


@pytest.mark.parametrize("policy", [optimize_dispatch, fixed_rule_dispatch])
@pytest.mark.parametrize("boundary,direction", [("soc_min", -1), ("soc_max", 1)])
def test_outside_soc_tolerance_still_rejected(state, config, policy, boundary, direction, monkeypatch):
    soc = getattr(config.battery, boundary) + direction * 2e-10
    state = state.model_copy(update={"battery_soc": soc})
    result = policy(state, config)
    assert result.plan is None
    assert result.error_code == "CURRENT_SOC_LIMIT"

    def forbidden(*args, **kwargs):
        raise AssertionError("Out-of-bounds SOC must be rejected before AC calculation")

    monkeypatch.setattr("power_engine.validator.run_power_flow", forbidden)
    plan = DispatchPlan(state_fingerprint=fingerprint(state), pv_power_kw=state.pv_available_kw,
                        battery_power_kw=0)
    verdict = validate_plan(state, plan, config)
    assert not verdict.passed
    assert "CURRENT_SOC_LIMIT" in {rule.code for rule in verdict.violated_rules}


@pytest.mark.integration
@pytest.mark.parametrize("policy", ["optimizer", "baseline"])
@pytest.mark.parametrize("initial_soc,direction", [(0.2, -1), (0.5, 1)])
def test_energy_limited_step_keeps_boundary_state_plannable(policy, initial_soc, direction):
    # Tiny test-only capacity makes one interval reach the bound with real IEEE-754 roundoff.
    cfg = MicrogridConfig(pv_available_kw=0, load_critical_kw=50, load_normal_kw=0,
                          battery={"capacity_kwh": 0.1, "initial_soc": initial_soc})
    sim = MicrogridSimulator(cfg)
    state = sim.get_state()
    charge, discharge = power_limits(state, cfg.battery, cfg.step_seconds)
    power = discharge if direction < 0 else -charge
    projected = project_soc(state.battery_soc, power, cfg.step_seconds, cfg.battery)
    plan = DispatchPlan(state_fingerprint=fingerprint(state), pv_power_kw=0,
                        battery_power_kw=power, duration_seconds=cfg.step_seconds)
    assert sim.apply_action(plan).status == "accepted"  # Real AC gate, not a stub.
    after, receipt = sim.step()
    assert receipt.status == "applied"
    assert after.battery_soc == projected  # Preserve the unrounded energy projection.
    if direction < 0:
        assert cfg.battery.soc_min - 1e-10 <= after.battery_soc < cfg.battery.soc_min
    else:
        assert cfg.battery.soc_max < after.battery_soc <= cfg.battery.soc_max + 1e-10
    for _ in range(3):
        result = control_step(sim, policy=policy)
        assert result["success"], result
        assert sim.get_state().critical_served_kw == cfg.load_critical_kw
    assert sim.get_state().state_revision == 4
