"""Energy accounting in kW, kWh, seconds and SOC 0..1; never silently clips SOC."""
import math

from power_engine.contracts import BatteryConfig, MicrogridState

SOC_TOL = 1e-10  # Shared numerical tolerance, not additional usable battery energy.


def soc_within_limits(soc: float, cfg: BatteryConfig) -> bool:
    """Accept only operating bounds plus roundoff; never clip or change the supplied SOC."""
    return cfg.soc_min - SOC_TOL <= soc <= cfg.soc_max + SOC_TOL


def project_soc(soc: float, power_kw: float, duration_seconds: float, cfg: BatteryConfig) -> float:
    if not all(math.isfinite(x) for x in (soc, power_kw, duration_seconds)):
        raise ValueError("SOC, power and duration must be finite")
    if not 0 <= soc <= 1 or duration_seconds <= 0:
        raise ValueError("SOC must be in [0, 1] and duration must be positive")
    hours = duration_seconds / 3600
    energy_kw = -power_kw / cfg.discharge_efficiency if power_kw >= 0 else -power_kw * cfg.charge_efficiency
    return soc + energy_kw * hours / cfg.capacity_kwh


def power_limits(state: MicrogridState, cfg: BatteryConfig, duration_seconds: float) -> tuple[float, float]:
    """Return (max charge, max discharge), intersecting energy, device and nameplate limits."""
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("duration must be positive and finite")
    hours = duration_seconds / 3600
    charge = max(0, (cfg.soc_max - state.battery_soc) * cfg.capacity_kwh / (hours * cfg.charge_efficiency))
    discharge = max(0, (state.battery_soc - cfg.soc_min) * cfg.capacity_kwh * cfg.discharge_efficiency / hours)
    return (min(charge, cfg.charge_max_kw, state.battery_charge_max_kw),
            min(discharge, cfg.discharge_max_kw, state.battery_discharge_max_kw))
