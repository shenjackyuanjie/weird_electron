"""CLI/experiment accounting tests; physical infeasibility is not an infrastructure failure."""
import json

import pytest

from power_engine.contracts import OptimizationResult, RuleViolation, ValidationResult, fingerprint
from simulator.cli import main, run_batch, run_episode
from simulator.controller import POLICIES, control_step
from simulator.simulator import MicrogridSimulator


def failing_gate(state, plan, cfg):
    return ValidationResult(request_id=plan.request_id, plan_id=plan.plan_id, passed=False,
                            state_fingerprint=fingerprint(state), plan_fingerprint=fingerprint(plan),
                            config_fingerprint=fingerprint(cfg),
                            violated_rules=(RuleViolation(code="DEPENDENCY_UNAVAILABLE", message="test-only missing dependency"),))


def test_computation_failure_is_not_retried_or_called_infeasible(monkeypatch, config):
    monkeypatch.setattr("simulator.controller.validate_plan", failing_gate)
    summary, trace = run_episode(config, "A")
    assert not summary["complete"]
    assert summary["failure_kind"] == "operational_error"
    assert summary["operational_error"]
    assert summary["error_code"] == "DEPENDENCY_UNAVAILABLE"
    assert len(trace) == len(trace[0]["attempts"]) == 1
    assert summary["critical_supply_ratio"] is None
    assert summary["execution_constraint_violation_rate"] is None
    assert summary["critical_requested_kwh"] == summary["critical_served_kwh"] == 0
    assert summary["observed_duration_seconds"] == 0


def test_batch_cli_errors_are_nonzero_and_logs_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr("simulator.controller.validate_plan", failing_gate)
    code = main(["batch", "--cases", "1", "--steps", "3", "--output", str(tmp_path)])
    assert code == 2
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["operational_errors"] == 2
    assert summary["incomplete"] == 2
    assert (tmp_path / "results.csv").exists()
    for policy in ("baseline", "optimizer"):
        assert (tmp_path / f"seed-000-{policy}" / "trace.jsonl").is_file()


def test_infeasible_cases_remain_observations(monkeypatch, tmp_path):
    def infeasible(*args, **kwargs):
        return OptimizationResult(status="infeasible", error_code="NO_FEASIBLE_DISPATCH")
    for name in ("baseline", "optimizer"):
        monkeypatch.setitem(POLICIES, name, infeasible)
    assert main(["batch", "--cases", "1", "--steps", "3", "--output", str(tmp_path)]) == 0
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["incomplete"] == 2 and summary["operational_errors"] == 0
    case = json.loads((tmp_path / "seed-000-optimizer" / "summary.json").read_text())
    assert case["failure_kind"] == "infeasible"
    assert case["critical_supply_ratio"] is None


def test_audit_counts_bad_intervals_not_number_of_rules(monkeypatch, config):
    # Synthetic control result tests summary arithmetic only, not an AC trajectory.
    state = MicrogridSimulator(config).get_state().wire()
    result = {"success": True, "before": state, "state": state, "receipt": {},
              "attempts": [{"validation": {"pass": True}, "plan": {"duration_seconds": 5}}],
              "operational_error": False}
    monkeypatch.setattr("simulator.cli.control_step", lambda *args: result.copy())
    monkeypatch.setattr("simulator.cli.audit_execution", lambda *args: {
        "passed": False, "violated_rules": ["ESS_DISCHARGE_LIMIT", "LINE_OVERLOAD"],
    })
    summary, trace = run_episode(config, "A", steps=3)
    assert summary["completed_intervals"] == 1
    assert summary["executed_constraint_violations"] == 1
    assert summary["execution_constraint_violation_rate"] == 1
    assert summary["failure_kind"] == "safety_violation"
    assert not summary["complete"] and summary["error_code"] == "EXECUTION_AUDIT_FAILED"
    assert summary["critical_supply_ratio"] is None
    assert summary["critical_served_kwh"] == pytest.approx(200 * 5 / 3600)
    assert len(trace[0]["execution_audit"]["violated_rules"]) == 2


@pytest.mark.parametrize("steps", [0, 2, True, 3.5])
def test_invalid_batch_steps_leave_no_output(tmp_path, steps):
    output = tmp_path / "not-created"
    with pytest.raises(ValueError):
        run_batch(output, cases=1, steps=steps)
    assert not output.exists()


@pytest.mark.parametrize("cases", [0, 10001, True, 1.5])
def test_invalid_batch_cases_leave_no_output(tmp_path, cases):
    output = tmp_path / "not-created"
    with pytest.raises(ValueError):
        run_batch(output, cases=cases, steps=3)
    assert not output.exists()


@pytest.mark.parametrize("replans", [True, 1.0, 3, -1])
def test_invalid_retry_count_is_value_error(replans):
    with pytest.raises(ValueError):
        control_step(MicrogridSimulator(), max_replans=replans)


def test_schema_export_includes_all_algorithm_results(tmp_path):
    assert main(["schemas", "--output", str(tmp_path)]) == 0
    assert len(list(tmp_path.glob("*.json"))) == 7
    for name in ("PowerFlowResult", "OptimizationResult", "ExecutionReceipt"):
        data = json.loads((tmp_path / f"{name}.json").read_text())
        assert data["title"] == name


@pytest.mark.integration
def test_real_receipt_contains_actual_second_gate_evidence(monkeypatch, config):
    from power_engine.validator import validate_plan
    def marked_execution_gate(*args):
        result = validate_plan(*args)
        if result.power_flow is not None:
            flow = result.power_flow.model_copy(update={"message": "actual-execution-verification"})
            result = result.model_copy(update={"power_flow": flow})
        return result
    monkeypatch.setattr("simulator.simulator.validate_plan", marked_execution_gate)
    summary, trace = run_episode(config, "A", steps=3)
    assert summary["complete"] and summary["execution_constraint_violation_rate"] == 0
    assert summary["observed_duration_seconds"] == 15
    for item in trace:
        assert item["receipt"]["validation"]["power_flow"]["message"] == "actual-execution-verification"
        assert item["attempts"][-1]["validation"]["power_flow"]["message"] is None
        assert item["execution_audit"]["passed"]
