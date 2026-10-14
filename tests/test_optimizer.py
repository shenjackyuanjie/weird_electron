import pytest

from power_engine.baseline import fixed_rule_dispatch
from power_engine.contracts import MicrogridConfig, fingerprint
from power_engine.optimizer import optimize_dispatch
from simulator.scenarios import initial_state, scenario_state


@pytest.mark.parametrize("scenario", ["normal", "A", "B", "C"])
@pytest.mark.parametrize("policy", [optimize_dispatch, fixed_rule_dispatch])
def test_lossless_feasible_candidates(state, config, scenario, policy):
    state = scenario_state(state, config, scenario)
    result = policy(state, config)
    assert result.plan is not None
    p = result.plan
    assert p.critical_shed_kw == 0
    assert p.state_fingerprint == fingerprint(state)
    assert p.pv_power_kw + p.battery_power_kw + p.expected_grid_kw == pytest.approx(
        state.load_critical_kw + state.load_normal_kw - p.normal_shed_kw)
    assert 0 <= p.normal_shed_kw <= state.normal_shed_max_kw


@pytest.mark.parametrize("policy", [optimize_dispatch, fixed_rule_dispatch])
def test_supply_insufficient(config, policy):
    cfg = MicrogridConfig(pv_available_kw=0, grid_import_max_kw=0, battery={"initial_soc": 0.1})
    result = policy(initial_state(cfg), cfg)
    assert result.status == "infeasible" and result.plan is None


@pytest.mark.parametrize("policy", [optimize_dispatch, fixed_rule_dispatch])
def test_charge_surplus(config, policy):
    cfg = MicrogridConfig(pv_available_kw=1000)
    result = policy(initial_state(cfg), cfg)
    assert result.plan.battery_power_kw == pytest.approx(-150)
    assert result.plan.normal_shed_kw == 0
    assert result.plan.pv_power_kw == pytest.approx(650)


@pytest.mark.parametrize("policy", [optimize_dispatch, fixed_rule_dispatch])
def test_full_battery_curtails(config, policy):
    cfg = MicrogridConfig(pv_available_kw=1000, battery={"initial_soc": 0.9})
    p = policy(initial_state(cfg), cfg).plan
    assert p.battery_power_kw == 0
    assert p.pv_power_kw == pytest.approx(500)


def test_frozen_inputs_and_json(state, config):
    before = state.model_dump_json()
    result = optimize_dispatch(state.wire(), config)
    assert result.plan is not None
    assert state.model_dump_json() == before


def test_island_rejected(state, config):
    result = optimize_dispatch(state.model_copy(update={"grid_available": False}), config)
    assert result.error_code == "UNSUPPORTED_ISLAND_MODE"


@pytest.mark.parametrize("duration", [0, -1, 301, float("nan")])
def test_invalid_horizon(state, config, duration):
    with pytest.raises(ValueError):
        optimize_dispatch(state, config, duration_seconds=duration)


def test_baseline_does_not_call_solver(monkeypatch, state, config):
    def forbidden(*args, **kwargs):
        raise AssertionError("Baseline must not call linprog")
    monkeypatch.setattr("power_engine.optimizer.linprog", forbidden)
    assert fixed_rule_dispatch(state, config).plan is not None
