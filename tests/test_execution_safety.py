"""Execution transaction unit tests. The fake gate tests locking, NOT electrical safety."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
import time

import pytest

from power_engine.battery import project_soc
from power_engine.contracts import (
    DispatchPlan, EngineError, PowerFlowResult, ValidationResult, fingerprint,
)
from power_engine.validator import validate_plan
from simulator.simulator import MicrogridSimulator


@pytest.fixture
def gate(monkeypatch):
    counts = {"calls": 0}
    counter_lock = Lock()
    def fake_gate(state, plan, cfg):
        with counter_lock:
            counts["calls"] += 1
        # Releases the GIL, making concurrent arrivals overlap unless protected by the lock.
        time.sleep(0.02)
        grid = state.load_critical_kw + state.load_normal_kw - plan.normal_shed_kw - plan.pv_power_kw - plan.battery_power_kw
        return ValidationResult(
            request_id=plan.request_id, plan_id=plan.plan_id, passed=True,
            state_fingerprint=fingerprint(state), plan_fingerprint=fingerprint(plan),
            config_fingerprint=fingerprint(cfg),
            predicted_soc=project_soc(state.battery_soc, plan.battery_power_kw, plan.duration_seconds, cfg.battery),
            power_flow=PowerFlowResult(converged=True, pcc_voltage_pu=1, min_voltage_pu=1,
                                       max_voltage_pu=1, grid_power_kw=grid, loss_kw=0,
                                       line_loading_percent=25, balance_residual_kw=0),
        )
    monkeypatch.setattr("simulator.simulator.validate_plan", fake_gate)
    return counts


def plan_for(sim):
    return DispatchPlan(state_fingerprint=fingerprint(sim.get_state()), pv_power_kw=350, battery_power_kw=60)


def test_duplicate_concurrent_acceptance_validates_once(gate):
    sim = MicrogridSimulator()
    plan = plan_for(sim)
    barrier = Barrier(4)
    def submit():
        barrier.wait(timeout=5)
        return sim.apply_action(plan)
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _: submit(), range(4)))
    assert all(receipt == receipts[0] for receipt in receipts)
    assert gate["calls"] == 1
    after, applied = sim.step()
    assert after.state_revision == 1
    assert applied.validation == receipts[0].validation
    assert sim.get_receipt(plan.plan_id) == applied


def test_concurrent_different_commands_cannot_overwrite_pending(gate):
    sim = MicrogridSimulator()
    plans = [plan_for(sim), plan_for(sim)]
    barrier = Barrier(2)
    def submit(plan):
        barrier.wait(timeout=5)
        try:
            return sim.apply_action(plan).status
        except EngineError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, plans))
    assert sorted(outcomes) == ["ACTION_PENDING", "accepted"]
    assert gate["calls"] == 1
    assert sum(sim.get_receipt(p.plan_id) is not None for p in plans) == 1


def test_only_one_concurrent_step_applies(gate):
    sim = MicrogridSimulator()
    sim.apply_action(plan_for(sim))
    barrier = Barrier(4)
    def step(_):
        barrier.wait(timeout=5)
        try:
            return sim.step()[1].status
        except EngineError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(step, range(4)))
    assert outcomes.count("applied") == 1
    assert outcomes.count("NO_PENDING_ACTION") == 3
    assert sim.get_state().state_revision == 1


def test_cancel_is_observable_and_does_not_advance_time(gate):
    sim = MicrogridSimulator()
    plan = plan_for(sim)
    before = sim.get_state()
    sim.apply_action(plan)
    cancelled = sim.cancel_pending_action()
    assert cancelled.status == "cancelled"
    assert sim.get_state() == before
    assert sim.get_receipt(plan.plan_id) == cancelled
    assert sim.apply_action(plan) == cancelled  # A cancelled ID is never replayed.
    assert sim.cancel_pending_action() is None
    assert sim.get_receipt("missing") is None
    sim.apply_action(plan_for(sim))
    assert sim.step()[1].status == "applied"
    sim.reset()
    assert sim.get_receipt(plan.plan_id) is None


def test_changed_config_can_cancel_and_replan(gate):
    sim = MicrogridSimulator()
    sim.apply_action(plan_for(sim))
    sim.config = sim.config.model_copy(update={"import_cost_per_kwh": 0.25})
    with pytest.raises(EngineError) as exc:
        sim.step()
    assert exc.value.code == "STALE_CONFIG"
    sim.cancel_pending_action()
    sim.apply_action(plan_for(sim))
    assert sim.step()[1].status == "applied"


def test_invalid_scenario_leaves_pending_intact(gate):
    sim = MicrogridSimulator()
    plan = plan_for(sim)
    sim.apply_action(plan)
    with pytest.raises(ValueError):
        sim.trigger_scenario("D")
    assert sim.get_receipt(plan.plan_id).status == "accepted"
    assert sim.step()[1].status == "applied"


@pytest.mark.parametrize("dt", [True, "5", [], float("nan")])
def test_bad_step_duration_does_not_consume_pending(gate, dt):
    sim = MicrogridSimulator()
    plan = plan_for(sim)
    sim.apply_action(plan)
    with pytest.raises(ValueError):
        sim.step(dt)
    assert sim.get_state().state_revision == 0
    assert sim.get_receipt(plan.plan_id).status == "accepted"
    assert sim.step()[1].status == "applied"


@pytest.mark.parametrize("raw", [
    {"converged": True},
    {"converged": True, "grid_power_kw": 0},
    {"converged": True, "grid_power_kw": float("nan")},
    None,
])
def test_malformed_flow_fails_closed(state, config, monkeypatch, raw):
    plan = DispatchPlan(state_fingerprint=fingerprint(state), pv_power_kw=350, battery_power_kw=60)
    monkeypatch.setattr("power_engine.validator.run_power_flow", lambda *args: raw)
    result = validate_plan(state, plan, config)
    assert not result.passed
    assert result.violated_rules[0].code == "INVALID_POWER_FLOW_RESULT"


@pytest.mark.parametrize("change", [
    {"error_code": "FAILED"}, {"loss_kw": None}, {"pcc_voltage_pu": 1.1},
])
def test_converged_result_requires_complete_consistent_data(change):
    values = dict(converged=True, pcc_voltage_pu=1, min_voltage_pu=1, max_voltage_pu=1,
                  grid_power_kw=0, loss_kw=0, line_loading_percent=0, balance_residual_kw=0)
    with pytest.raises(ValueError):
        PowerFlowResult(**(values | change))
