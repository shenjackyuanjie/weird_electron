"""Phase-2 no-Agent loop. One replan maximum by default; failed cases stop explicitly."""
from power_engine.baseline import fixed_rule_dispatch
from power_engine.contracts import EngineError
from power_engine.optimizer import optimize_dispatch
from power_engine.validator import validate_plan

POLICIES = {"optimizer": optimize_dispatch, "baseline": fixed_rule_dispatch}


def control_step(simulator, policy="optimizer", max_replans=1) -> dict:
    if policy not in POLICIES or max_replans not in (0, 1, 2):
        raise ValueError("Unknown policy or unsupported retry count")
    state = simulator.get_state()
    attempts = []
    feedback = None
    for _ in range(max_replans + 1):
        candidate = POLICIES[policy](state, simulator.config, feedback=feedback)
        if candidate.plan is None:
            return {"success": False, "error_code": candidate.error_code, "state": state.wire(),
                    "attempts": attempts, "optimization": candidate.wire()}
        validation = validate_plan(state, candidate.plan, simulator.config)
        attempts.append({"plan": candidate.plan.wire(), "validation": validation.wire()})
        if validation.passed:
            try:
                simulator.apply_action(candidate.plan)
                after, receipt = simulator.step()
            except EngineError as exc:
                return {"success": False, "error_code": exc.code, "state": state.wire(), "attempts": attempts}
            return {"success": True, "before": state.wire(), "state": after.wire(),
                    "receipt": receipt.wire(), "attempts": attempts}
        feedback = validation
    return {"success": False, "error_code": "VALIDATION_REJECTED", "state": state.wire(), "attempts": attempts}
