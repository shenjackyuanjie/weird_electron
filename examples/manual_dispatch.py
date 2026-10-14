"""Complete JSON-adapter chain, including one bounded feedback retry and real execution.

From the repository root: python -m examples.manual_dispatch
"""
import json

from power_engine.api import invoke
from simulator.metrics import audit_execution
from simulator.simulator import MicrogridSimulator


def run_manual() -> dict:
    sim = MicrogridSimulator()
    sim.trigger_scenario("A")
    before = sim.get_state().wire()
    payload = {"state": before, "request_id": "manual-example"}
    attempts = []
    for _ in range(2):  # Initial proposal plus at most one replan.
        proposal = invoke("optimize_dispatch", payload, sim.config)
        if not proposal["ok"]:
            raise RuntimeError(proposal)
        optimization = proposal["result"]
        if optimization["plan"] is None:
            raise RuntimeError(optimization)
        plan = optimization["plan"]
        response = invoke("validate_plan", {"state": before, "plan": plan}, sim.config)
        if not response["ok"]:
            raise RuntimeError(response)
        validation = response["result"]
        attempts.append({"plan": plan, "validation": validation})
        if validation["pass"]:
            accepted = sim.apply_action(plan)  # Independent gate again, using actual state.
            if sim.apply_action(plan) != accepted:  # Same ID and content: no second execution.
                raise RuntimeError("Idempotent acceptance changed the receipt")
            after, receipt = sim.step()
            if sim.get_receipt(plan["plan_id"]) != receipt:
                raise RuntimeError("Stored receipt differs from applied receipt")
            audit = audit_execution(before, after, plan, receipt, sim.config)
            if not audit["passed"]:
                raise RuntimeError(audit)
            return {"attempts": attempts, "accepted": accepted.wire(),
                    "state": after.wire(), "receipt": receipt.wire(), "execution_audit": audit}
        payload["feedback"] = validation
    raise RuntimeError({"error_code": "VALIDATION_REJECTED", "attempts": attempts})


if __name__ == "__main__":
    print(json.dumps(run_manual(), indent=2, ensure_ascii=False, allow_nan=False))
