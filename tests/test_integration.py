import json

import pytest

from power_engine.contracts import DispatchPlan, EngineError, MicrogridConfig, fingerprint
from power_engine.optimizer import optimize_dispatch
from power_engine.power_flow import run_power_flow
from power_engine.validator import validate_plan
from simulator.cli import run_batch, run_episode
from simulator.controller import control_step
from simulator.simulator import MicrogridSimulator

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("scenario", ["A", "B", "C"])
@pytest.mark.parametrize("policy", ["optimizer", "baseline"])
def test_three_real_closed_loops(config, scenario, policy):
    summary, trace = run_episode(config, scenario, policy=policy, steps=4)
    assert summary["complete"], trace[-1]
    assert summary["executed_constraint_violations"] == 0
    assert summary["critical_supply_ratio"] == pytest.approx(1)
    assert trace[-1]["state"]["scenario_id"] == "normal"
    assert trace[-1]["state"]["battery_soc"] < config.battery.initial_soc


def test_real_ac_sign_losses_and_no_mutation(state, config):
    plan = DispatchPlan(state_fingerprint=fingerprint(state), pv_power_kw=350, battery_power_kw=50)
    before = state.model_dump_json()
    flow = run_power_flow(state, plan, config)
    assert flow.converged, flow
    assert flow.grid_power_kw > 100  # Feeder losses are real, not silently ignored.
    assert flow.loss_kw > 0
    assert abs(flow.balance_residual_kw) < 0.02
    charging = plan.model_copy(update={"battery_power_kw": -50})
    assert run_power_flow(state, charging, config).grid_power_kw > flow.grid_power_kw + 100
    assert state.model_dump_json() == before


def test_actual_grid_cap_rejected_then_replanned(state, config):
    first = optimize_dispatch(state, config).plan
    rejected = validate_plan(state, first, config)
    assert not rejected.passed
    assert "GRID_IMPORT_LIMIT" in {r.code for r in rejected.violated_rules}
    second = optimize_dispatch(state, config, feedback=rejected).plan
    assert second.battery_power_kw != first.battery_power_kw
    assert validate_plan(state, second, config).passed


@pytest.mark.parametrize("grid_voltage,code", [(0.9, "VOLTAGE_LOW"), (1.1, "VOLTAGE_HIGH")])
def test_voltage_boundaries(state, config, grid_voltage, code):
    state = state.model_copy(update={"grid_voltage_pu": grid_voltage})
    result = validate_plan(state, optimize_dispatch(state, config).plan, config)
    assert code in {r.code for r in result.violated_rules}


def test_line_overload(state):
    cfg = MicrogridConfig(network={"max_current_ka": 0.01})
    result = validate_plan(state, optimize_dispatch(state, cfg).plan, cfg)
    assert "LINE_OVERLOAD" in {r.code for r in result.violated_rules}


def test_solver_exception_fails_closed(monkeypatch, state, config):
    import pandapower
    def fail(*args, **kwargs):
        raise RuntimeError("deliberate solver failure")
    monkeypatch.setattr(pandapower, "runpp", fail)
    result = validate_plan(state, optimize_dispatch(state, config).plan, config)
    assert not result.passed
    assert result.violated_rules[0].code == "POWER_FLOW_FAILED"


def safe_plan(sim):
    s = sim.get_state()
    first = optimize_dispatch(s, sim.config).plan
    validation = validate_plan(s, first, sim.config)
    return first if validation.passed else optimize_dispatch(s, sim.config, feedback=validation).plan


def test_ack_then_step_and_idempotency(config):
    sim = MicrogridSimulator(config)
    plan = safe_plan(sim)
    before = sim.get_state()
    ack = sim.apply_action(plan)
    assert ack.status == "accepted" and sim.get_state() == before
    assert sim.apply_action(plan) == ack
    after, receipt = sim.step()
    assert receipt.status == "applied"
    assert after.battery_soc < before.battery_soc
    assert (after.timestamp - before.timestamp).total_seconds() == 5
    assert sim.apply_action(plan) == receipt
    with pytest.raises(EngineError, match="required"):
        sim.step()
    with pytest.raises(EngineError, match="different content"):
        sim.apply_action(plan.model_copy(update={"battery_power_kw": 1}))


def test_execution_rejects_unsafe_and_stale(config):
    sim = MicrogridSimulator(config)
    plan = safe_plan(sim)
    with pytest.raises(EngineError, match="ESS_DISCHARGE_LIMIT"):
        sim.apply_action(plan.model_copy(update={"battery_power_kw": 500}))
    sim.trigger_scenario("C")
    with pytest.raises(EngineError, match="STALE_STATE"):
        sim.apply_action(plan)


def test_duration_and_reset_replay(config):
    sim = MicrogridSimulator(config)
    plan = safe_plan(sim)
    sim.apply_action(plan)
    with pytest.raises(EngineError, match="duration"):
        sim.step(300)
    sim.reset()
    with pytest.raises(EngineError, match="STALE_STATE"):
        sim.apply_action(plan)


def test_fails_without_advancing_or_cutting_critical(config):
    cfg = MicrogridConfig(pv_available_kw=0, grid_import_max_kw=0, battery={"initial_soc": 0.1})
    sim = MicrogridSimulator(cfg)
    before = sim.get_state()
    result = control_step(sim)
    assert not result["success"]
    assert sim.get_state() == before


def test_batch_preserves_paired_seeds_and_errors(tmp_path):
    summary = run_batch(tmp_path, cases=3, steps=3)
    assert summary["episodes"] == 6
    assert (tmp_path / "results.csv").is_file()
    for seed in range(3):
        root = tmp_path / f"seed-{seed:03d}"
        base = json.loads((root.with_name(root.name + "-baseline") / "config.json").read_text())
        opt = json.loads((root.with_name(root.name + "-optimizer") / "config.json").read_text())
        assert base == opt


def test_scenario_cancels_pending_receipt(config):
    sim = MicrogridSimulator(config)
    plan = safe_plan(sim)
    sim.apply_action(plan)
    sim.trigger_scenario("C")
    assert sim.apply_action(plan).status == "cancelled"
    with pytest.raises(EngineError, match="required"):
        sim.step()


def test_nonfinite_ac_result_is_not_safe(monkeypatch, state, config):
    import pandapower
    original = pandapower.runpp
    def nonfinite(net, **kwargs):
        original(net, **kwargs)
        net.res_bus.loc[:, "vm_pu"] = float("nan")
    monkeypatch.setattr(pandapower, "runpp", nonfinite)
    result = validate_plan(state, optimize_dispatch(state, config).plan, config)
    assert not result.passed
    assert result.violated_rules[0].code == "POWER_FLOW_FAILED"


def test_export_cap_is_checked(state, config):
    state = state.model_copy(update={"pv_available_kw": 800})
    plan = DispatchPlan(state_fingerprint=fingerprint(state), pv_power_kw=800, battery_power_kw=0)
    result = validate_plan(state, plan, config)
    assert "GRID_EXPORT_LIMIT" in {r.code for r in result.violated_rules}
