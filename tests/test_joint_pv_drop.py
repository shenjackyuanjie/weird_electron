"""Offline handoff examples: real AC results, not live C/AgentArts integration."""
import json
from pathlib import Path

import pytest

from examples.joint_pv_drop import build_cases, fixture_inputs, proposed_c_telemetry, write_cases
from power_engine.api import invoke
from power_engine.contracts import DispatchPlan, MicrogridConfig, MicrogridState, fingerprint


def test_joint_profile_disables_non_ess_actions():
    config, state = fixture_inputs()
    assert config.pv_available_kw == 350
    assert state.pv_available_kw == 100
    assert state.load_critical_kw + state.load_normal_kw == 350
    assert state.normal_shed_max_kw == 0
    assert state.battery_soc == 0.6
    assert state.battery_power_kw == 0
    assert state.pcc_voltage_pu is None


def test_fixture_snapshot_is_fully_materialized_and_repeatable():
    config, state = fixture_inputs()
    assert state.wire() == fixture_inputs()[1].wire()
    assert fingerprint(state) == fingerprint(MicrogridState.model_validate(state.wire()))
    assert fingerprint(config) == fingerprint(MicrogridConfig.model_validate(config.wire()))
    assert set(MicrogridState.model_fields) == set(state.wire())


def test_c_envelope_is_only_a_proposal_not_an_existing_state_field():
    _, state = fixture_inputs()
    sample = proposed_c_telemetry(state)
    assert sample["soc"] == state.battery_soc
    assert sample["power_kw"] == state.battery_power_kw
    assert sample["charge_max_kw"] == state.battery_charge_max_kw
    assert sample["discharge_max_kw"] == state.battery_discharge_max_kw
    assert "online" not in state.wire()
    assert sample["positive_power"] == "discharge"
    assert sample["soc_unit"] == "ratio"


@pytest.fixture(scope="module")
def cases():
    return build_cases()


@pytest.mark.integration
def test_real_ac_reject_then_pass_on_identical_snapshot(cases):
    first, retry = cases["initial"], cases["replan"]
    assert first["validate_request"]["state"] == retry["validate_request"]["state"]
    assert not first["validate_response"]["result"]["pass"]
    assert first["validate_response"]["result"]["power_flow"]["converged"]
    assert retry["validate_response"]["result"]["pass"]
    assert retry["validate_response"]["result"]["power_flow"]["converged"]
    assert retry["optimize_request"]["feedback"] == first["validate_response"]["result"]
    assert first["validate_request"]["plan"]["plan_id"] != retry["validate_request"]["plan"]["plan_id"]
    for case in (first, retry):
        plan = case["optimize_response"]["result"]["plan"]
        assert case["validate_request"]["plan"] == plan
        assert plan["request_id"] == case["optimize_request"]["request_id"]
        assert plan["normal_shed_kw"] == plan["critical_shed_kw"] == 0
        assert plan["pv_power_kw"] == cases["state"]["pv_available_kw"]


@pytest.mark.integration
@pytest.mark.parametrize("key,passed", [("initial", False), ("replan", True), ("hard_reject", False)])
def test_exported_json_requests_replay_real_validator(cases, key, passed):
    config = MicrogridConfig.model_validate(cases["config"])
    payload = json.loads(json.dumps(cases[key]["validate_request"], allow_nan=False))
    actual = invoke("validate_plan", payload, config)
    assert actual["ok"] and actual["result"]["pass"] is passed
    saved = cases[key]["validate_response"]["result"]
    assert {r["code"] for r in actual["result"]["violated_rules"]} == {r["code"] for r in saved["violated_rules"]}
    assert actual["result"]["plan_fingerprint"] == fingerprint(DispatchPlan.model_validate(payload["plan"]))
    if passed:
        assert actual["result"]["power_flow"]["grid_power_kw"] == pytest.approx(saved["power_flow"]["grid_power_kw"])


@pytest.mark.integration
def test_hard_reject_does_not_claim_ac_ran(cases):
    verdict = cases["hard_reject"]["validate_response"]["result"]
    assert not verdict["pass"] and verdict["power_flow"] is None
    assert "ESS_DISCHARGE_LIMIT" in {r["code"] for r in verdict["violated_rules"]}


@pytest.mark.integration
def test_changed_snapshot_invalidates_fixture_plan(cases):
    payload = json.loads(json.dumps(cases["replan"]["validate_request"]))
    payload["state"]["state_revision"] += 1
    result = invoke("validate_plan", payload, MicrogridConfig.model_validate(cases["config"]))
    assert result["ok"] and not result["result"]["pass"]
    assert "STALE_STATE" in {r["code"] for r in result["result"]["violated_rules"]}
    assert result["result"]["power_flow"] is None


@pytest.mark.integration
def test_missing_soc_is_input_error_not_a_validator_reject(cases):
    payload = json.loads(json.dumps(cases["initial"]["optimize_request"]))
    del payload["state"]["battery_soc"]
    response = invoke("optimize_dispatch", payload, MicrogridConfig.model_validate(cases["config"]))
    assert response["ok"] is False and response["error_code"] == "INVALID_INPUT"


@pytest.mark.integration
def test_write_handoff_artifacts(cases, tmp_path):
    write_cases(tmp_path, cases)
    assert json.loads((tmp_path / "bundle.json").read_text(encoding="utf-8")) == cases
    assert len(list(tmp_path.glob("*.json"))) == 14
    # Existing CI uploads outputs/; no cloud/CI permission changes are needed.
    write_cases(Path("outputs/joint-pv-drop"), cases)
