"""Phase-2 no-Agent loop. One replan maximum; physical refusal is not a runtime failure."""
from power_engine.baseline import fixed_rule_dispatch
from power_engine.contracts import EngineError
from power_engine.optimizer import optimize_dispatch
from power_engine.validator import validate_plan

POLICIES = {"optimizer": optimize_dispatch, "baseline": fixed_rule_dispatch}
COMPUTATION_ERRORS = {
    "POWER_FLOW_FAILED", "DEPENDENCY_UNAVAILABLE", "INVALID_POWER_FLOW_RESULT",
    "STALE_STATE", "UNSUPPORTED_ISLAND_MODE",
}


def control_step(simulator, policy="optimizer", max_replans=1) -> dict:
    if not isinstance(policy, str) or policy not in POLICIES or type(max_replans) is not int or max_replans not in (0, 1, 2):
        raise ValueError("Unknown policy or unsupported retry count")
    state = simulator.get_state()
    attempts = []
    feedback = None

    def failed(code, *, operational=True, **extra):
        return {"success": False, "error_code": code, "before": state.wire(),
                "state": simulator.get_state().wire(), "attempts": attempts,
                "operational_error": operational, **extra}

    for _ in range(max_replans + 1):
        try:
            candidate = POLICIES[policy](state, simulator.config, feedback=feedback)
            if candidate.plan is None:
                return failed(candidate.error_code,
                              operational=candidate.status != "infeasible",
                              optimization=candidate.wire())
            validation = validate_plan(state, candidate.plan, simulator.config)
        except (EngineError, ValueError) as exc:
            return failed(getattr(exc, "code", "INVALID_ENGINE_RESULT"), message=str(exc))
        attempts.append({"plan": candidate.plan.wire(), "validation": validation.wire(),
                         "optimization_status": candidate.status, "objective": candidate.objective})
        if validation.passed:
            try:
                simulator.apply_action(candidate.plan)
                after, receipt = simulator.step()
            except (EngineError, ValueError) as exc:
                return failed(getattr(exc, "code", "EXECUTION_FAILED"), message=str(exc))
            return {"success": True, "before": state.wire(), "state": after.wire(),
                    "receipt": receipt.wire(), "attempts": attempts, "operational_error": False}
        fatal_codes = [r.code for r in validation.violated_rules if r.code in COMPUTATION_ERRORS]
        if fatal_codes:
            return failed(fatal_codes[0])  # Replanning cannot install a dependency or repair a solver.
        feedback = validation
    return failed("VALIDATION_REJECTED", operational=False)
