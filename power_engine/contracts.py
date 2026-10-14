"""Shared wire models. Change docs/contracts.md before changing this module."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, model_validator

NonNegative = Annotated[float, Field(ge=0)]
Positive = Annotated[float, Field(gt=0)]
Fraction = Annotated[float, Field(ge=0, le=1)]
Duration = Annotated[float, Field(gt=0, le=300, strict=True)]
Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=128, pattern=r"\S")]
DURATION_ADAPTER = TypeAdapter(Duration)
IDENTIFIER_ADAPTER = TypeAdapter(Identifier)


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, populate_by_name=True)

    def wire(self) -> dict:
        return self.model_dump(mode="json", by_alias=True)


def checked(cls, value):
    """Revalidate even model_copy(update=...) objects crossing a public boundary."""
    return cls.model_validate(value.wire() if isinstance(value, WireModel) else value)


def fingerprint(value: WireModel) -> str:
    data = json.dumps(value.wire(), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


class BatteryConfig(WireModel):
    capacity_kwh: Positive = 500
    soc_min: Fraction = 0.1
    soc_max: Fraction = 0.9
    initial_soc: Fraction = 0.6
    charge_efficiency: Annotated[float, Field(gt=0, le=1)] = 0.95
    discharge_efficiency: Annotated[float, Field(gt=0, le=1)] = 0.95
    charge_max_kw: NonNegative = 150
    discharge_max_kw: NonNegative = 200

    @model_validator(mode="after")
    def ordered_soc(self):
        if not self.soc_min <= self.initial_soc <= self.soc_max or self.soc_min >= self.soc_max:
            raise ValueError("Require soc_min <= initial_soc <= soc_max and soc_min < soc_max")
        return self


class NetworkConfig(WireModel):
    nominal_kv: Positive = 0.4
    length_km: Positive = 0.08
    r_ohm_per_km: Positive = 0.125
    x_ohm_per_km: NonNegative = 0.08
    max_current_ka: Positive = 0.6
    load_power_factor: Annotated[float, Field(gt=0, le=1)] = 0.98
    voltage_min_pu: Positive = 0.95
    voltage_max_pu: Positive = 1.05
    loading_max_percent: Positive = 100

    @model_validator(mode="after")
    def voltage_order(self):
        if self.voltage_min_pu >= self.voltage_max_pu:
            raise ValueError("voltage_min_pu must be below voltage_max_pu")
        return self


class MicrogridConfig(WireModel):
    battery: BatteryConfig = Field(default_factory=BatteryConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    step_seconds: Duration = 5
    pv_available_kw: NonNegative = 350
    load_critical_kw: NonNegative = 200
    load_normal_kw: NonNegative = 300
    grid_import_max_kw: NonNegative = 100
    grid_export_max_kw: NonNegative = 0
    grid_voltage_pu: Positive = 1
    nominal_frequency_hz: Positive = 50
    import_cost_per_kwh: Positive = 0.18
    curtail_cost_per_kwh: Positive = 1
    shed_cost_per_kwh: Positive = 1000
    battery_cost_per_kwh: Positive = 0.22


class MicrogridState(WireModel):
    schema_version: Literal["0.1"] = "0.1"
    microgrid_id: str = "gridguardian-demo"
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    state_revision: int = Field(default=0, ge=0)
    timestamp: AwareDatetime = Field(default_factory=lambda: datetime.fromisoformat("2026-10-14T00:00:00+09:00"))
    scenario_id: Literal["normal", "A", "B", "C"] = "normal"
    pv_available_kw: NonNegative
    pv_power_kw: NonNegative
    load_critical_kw: NonNegative
    load_normal_kw: NonNegative
    critical_served_kw: NonNegative
    normal_served_kw: NonNegative
    normal_shed_max_kw: NonNegative
    battery_soc: Fraction
    battery_power_kw: float = 0
    battery_charge_max_kw: NonNegative
    battery_discharge_max_kw: NonNegative
    grid_import_max_kw: NonNegative
    grid_export_max_kw: NonNegative = 0
    grid_available: bool = True
    grid_voltage_pu: Positive = 1
    frequency_hz: Positive = 50
    alarm_code: str | None = None
    pcc_voltage_pu: Positive | None = None
    grid_power_kw: float | None = None

    @model_validator(mode="after")
    def demand_limits(self):
        if self.normal_shed_max_kw > self.load_normal_kw:
            raise ValueError("normal_shed_max_kw cannot exceed normal demand")
        if self.normal_served_kw > self.load_normal_kw or self.critical_served_kw > self.load_critical_kw:
            raise ValueError("served load cannot exceed demand")
        if self.pv_power_kw > self.pv_available_kw:
            raise ValueError("actual PV cannot exceed available PV")
        return self


class DispatchPlan(WireModel):
    schema_version: Literal["0.1"] = "0.1"
    request_id: Identifier = Field(default_factory=lambda: str(uuid4()))
    plan_id: Identifier = Field(default_factory=lambda: str(uuid4()))
    state_fingerprint: str = Field(min_length=64, max_length=64)
    duration_seconds: Duration = 5
    pv_power_kw: NonNegative
    battery_power_kw: float  # Positive = discharge; negative = charge.
    normal_shed_kw: NonNegative = 0
    critical_shed_kw: NonNegative = 0  # Validator always rejects nonzero values.
    expected_grid_kw: float | None = None  # Advisory LP estimate, NOT a device command.


class PowerFlowResult(WireModel):
    converged: bool
    error_code: str | None = None
    message: str | None = None
    pcc_voltage_pu: Positive | None = None
    min_voltage_pu: Positive | None = None
    max_voltage_pu: Positive | None = None
    line_loading_percent: NonNegative | None = None
    grid_power_kw: float | None = None
    loss_kw: NonNegative | None = None
    balance_residual_kw: float | None = None


    @model_validator(mode="after")
    def usable_converged_result(self):
        if self.converged:
            fields = (self.pcc_voltage_pu, self.min_voltage_pu, self.max_voltage_pu,
                      self.line_loading_percent, self.grid_power_kw, self.loss_kw,
                      self.balance_residual_kw)
            if self.error_code is not None or any(value is None for value in fields):
                raise ValueError("Converged power flow requires every electrical result and no error")
            if not self.min_voltage_pu <= self.pcc_voltage_pu <= self.max_voltage_pu:
                raise ValueError("PCC voltage must lie within the reported bus voltage range")
        return self


class RuleViolation(WireModel):
    code: str
    message: str
    actual: float | None = None
    limit: float | None = None


class ValidationResult(WireModel):
    request_id: Identifier
    plan_id: Identifier
    passed: bool = Field(alias="pass")
    state_fingerprint: str
    plan_fingerprint: str
    config_fingerprint: str
    violated_rules: tuple[RuleViolation, ...] = ()
    predicted_soc: float | None = None
    power_flow: PowerFlowResult | None = None


class OptimizationResult(WireModel):
    status: Literal["optimal", "feasible", "infeasible", "error"]
    plan: DispatchPlan | None = None
    objective: float | None = None
    error_code: str | None = None
    message: str | None = None


class ExecutionReceipt(WireModel):
    request_id: Identifier
    plan_id: Identifier
    status: Literal["accepted", "applied", "cancelled"]
    timestamp: AwareDatetime
    state_revision: int
    plan_fingerprint: str
    validation: ValidationResult | None = None


class EngineError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
