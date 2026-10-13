"""One accepted plan drives one simulation interval; no hidden time or silent clipping."""
from datetime import timedelta

from power_engine.contracts import (
    DispatchPlan, EngineError, ExecutionReceipt, MicrogridConfig,
    MicrogridState, checked, fingerprint,
)
from power_engine.validator import validate_plan
from simulator.scenarios import initial_state, scenario_state


class MicrogridSimulator:
    def __init__(self, config: MicrogridConfig | None = None):
        self.config = checked(MicrogridConfig, config or MicrogridConfig())
        self.reset()

    def reset(self) -> MicrogridState:
        self._state = initial_state(self.config)  # New run_id prevents replay across resets.
        self._pending = None
        self._receipts = {}
        return self._state

    def get_state(self) -> MicrogridState:
        return self._state

    def trigger_scenario(self, scenario_id: str, severity: float | None = None) -> MicrogridState:
        self._state = scenario_state(self._state, self.config, scenario_id, severity)
        if self._pending is not None:
            plan, _ = self._pending
            previous = self._receipts[plan.plan_id]
            self._receipts[plan.plan_id] = previous.model_copy(update={
                "status": "cancelled", "timestamp": self._state.timestamp,
                "state_revision": self._state.state_revision,
            })
        self._pending = None  # Accepted commands for the old observation are no longer valid.
        return self._state

    def apply_action(self, plan) -> ExecutionReceipt:
        plan = checked(DispatchPlan, plan)
        digest = fingerprint(plan)
        previous = self._receipts.get(plan.plan_id)
        if previous:
            if previous.plan_fingerprint != digest:
                raise EngineError("IDEMPOTENCY_CONFLICT", "plan_id was reused with different content")
            return previous
        if self._pending is not None:
            raise EngineError("ACTION_PENDING", "Apply the pending interval before accepting another plan")
        result = validate_plan(self._state, plan, self.config)  # Do not trust caller-supplied approval.
        if not result.passed:
            raise EngineError("UNSAFE_PLAN", ", ".join(r.code for r in result.violated_rules))
        receipt = ExecutionReceipt(request_id=plan.request_id, plan_id=plan.plan_id, status="accepted",
                                   timestamp=self._state.timestamp, state_revision=self._state.state_revision,
                                   plan_fingerprint=digest)
        self._pending = (plan, result)
        self._receipts[plan.plan_id] = receipt
        return receipt

    def step(self, dt_seconds: float | None = None) -> tuple[MicrogridState, ExecutionReceipt]:
        if self._pending is None:
            raise EngineError("NO_PENDING_ACTION", "A validated single-interval plan is required")
        plan, validation = self._pending
        dt = plan.duration_seconds if dt_seconds is None else dt_seconds
        if dt != plan.duration_seconds:
            raise EngineError("DURATION_MISMATCH", "Execution duration must equal the validated duration")
        if validation.state_fingerprint != fingerprint(self._state):
            raise EngineError("STALE_STATE", "State changed after command acceptance")
        if validation.config_fingerprint != fingerprint(self.config):
            raise EngineError("STALE_CONFIG", "Configuration changed after command acceptance")
        # State and config are immutable and match the independently validated snapshot.
        data = self._state.wire()
        data.update(timestamp=self._state.timestamp + timedelta(seconds=dt),
                    state_revision=self._state.state_revision + 1, battery_soc=validation.predicted_soc,
                    battery_power_kw=plan.battery_power_kw, pv_power_kw=plan.pv_power_kw,
                    critical_served_kw=self._state.load_critical_kw,
                    normal_served_kw=self._state.load_normal_kw - plan.normal_shed_kw,
                    pcc_voltage_pu=validation.power_flow.pcc_voltage_pu,
                    grid_power_kw=validation.power_flow.grid_power_kw)
        next_state = MicrogridState.model_validate(data)
        receipt = ExecutionReceipt(request_id=plan.request_id, plan_id=plan.plan_id, status="applied",
                                   timestamp=next_state.timestamp, state_revision=next_state.state_revision,
                                   plan_fingerprint=fingerprint(plan))
        self._state = next_state
        self._receipts[plan.plan_id] = receipt
        self._pending = None
        return self._state, receipt
