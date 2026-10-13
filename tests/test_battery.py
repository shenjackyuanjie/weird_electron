import math

import pytest

from power_engine.battery import power_limits, project_soc
from power_engine.contracts import BatteryConfig


def test_discharge_energy():
    cfg = BatteryConfig(capacity_kwh=100, discharge_efficiency=0.8)
    assert project_soc(0.5, 10, 3600, cfg) == pytest.approx(0.375)


def test_charge_energy():
    cfg = BatteryConfig(capacity_kwh=100, charge_efficiency=0.8)
    assert project_soc(0.5, -10, 3600, cfg) == pytest.approx(0.58)


def test_idle(config):
    assert project_soc(0.6, 0, 5, config.battery) == 0.6


def test_never_clips(config):
    assert project_soc(0.1, 200, 3600, config.battery) < config.battery.soc_min


@pytest.mark.parametrize("duration", [0, -5, math.nan, math.inf])
def test_invalid_duration(config, duration):
    with pytest.raises(ValueError):
        project_soc(0.5, 1, duration, config.battery)


@pytest.mark.parametrize("power", [math.nan, math.inf, -math.inf])
def test_nonfinite_power(config, power):
    with pytest.raises(ValueError):
        project_soc(0.5, power, 5, config.battery)


def test_power_bounds_near_empty(state, config):
    state = state.model_copy(update={"battery_soc": 0.10001})
    charge, discharge = power_limits(state, config.battery, 300)
    assert discharge < 1
    assert project_soc(state.battery_soc, discharge, 300, config.battery) == pytest.approx(0.1)
    assert charge <= config.battery.charge_max_kw


def test_hardware_limits_cannot_be_inflated(state, config):
    state = state.model_copy(update={"battery_discharge_max_kw": 1e6})
    assert power_limits(state, config.battery, 5)[1] == config.battery.discharge_max_kw


def test_soc_bounds_config():
    with pytest.raises(ValueError):
        BatteryConfig(soc_min=0.8, soc_max=0.2)
