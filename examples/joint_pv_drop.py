"""Export B-line PV-drop contract fixtures using real optimizer and AC validation.

No network, C telemetry ingestion, device commands, or production runtime changes.
The proposed C envelope and the synthetic clock are NOT live telemetry/approval.
"""
import argparse
import json
import platform
from importlib.metadata import version
from pathlib import Path

from power_engine.api import invoke
from power_engine.contracts import MicrogridConfig, MicrogridState, fingerprint
from simulator.scenarios import initial_state, scenario_state

RUNTIME_BASE = "494508a0335cdcabf5496c28cdf3db26d5c52db8"
REQUEST_ID = "joint-pv-drop-001"


def fixture_inputs():
    """Proposed first-test profile: 350 -> 100 kW PV, 350 kW demand, no shedding."""
    config = MicrogridConfig(load_normal_kw=150)
    state = initial_state(config)
    state = MicrogridState.model_validate({
        **state.wire(), "microgrid_id": "gridhive-joint-demo",
        "run_id": "joint-pv-drop-fixture", "timestamp": "2026-10-15T00:00:00+09:00",
        "normal_shed_max_kw": 0.0,
    })
    return config, scenario_state(state, config, "A")


def proposed_c_telemetry(state):
    """A discussion-only normalized envelope, not C's actual IoTDA response."""
    return {
        "device_id": "ess-virtual-demo", "boot_id": "fixture-boot-001", "sequence": 1,
        "measured_at": state.wire()["timestamp"], "online": True,
        "soc": state.battery_soc, "soc_unit": "ratio", "power_kw": state.battery_power_kw,
        "positive_power": "discharge", "power_unit": "kW",
        "charge_max_kw": state.battery_charge_max_kw,
        "discharge_max_kw": state.battery_discharge_max_kw,
        "profile_id": "joint-ess-proposed-v1",
    }


def build_cases():
    config, state_model = fixture_inputs()
    state = state_model.wire()
    before = json.dumps(state, sort_keys=True)

    def call(tool, payload):
        response = invoke(tool, payload, config)
        if not response["ok"]:
            raise RuntimeError(f"Fixture tool failure: {response}")
        return response

    def candidate(payload):
        response = call("optimize_dispatch", payload)
        plan = response["result"].get("plan")
        if response["result"]["status"] != "optimal" or plan is None:
            raise RuntimeError(f"Fixture must have a candidate: {response}")
        if (plan["normal_shed_kw"] != 0 or plan["critical_shed_kw"] != 0
                or plan["pv_power_kw"] != state["pv_available_kw"]):
            raise RuntimeError("First joint profile must not require load/PV actuation")
        return response, plan

    first_request = {"request_id": REQUEST_ID, "state": state, "duration_seconds": 5.0}
    first_response, first_plan = candidate(first_request)
    reject_request = {"request_id": REQUEST_ID, "state": state, "plan": first_plan}
    reject_response = call("validate_plan", reject_request)
    rejection = reject_response["result"]
    if (rejection["pass"] or not rejection.get("power_flow")
            or not rejection["power_flow"]["converged"]
            or "GRID_IMPORT_LIMIT" not in {r["code"] for r in rejection["violated_rules"]}):
        raise RuntimeError(f"Expected a real AC PCC-limit rejection: {reject_response}")

    retry_request = {**first_request, "feedback": rejection}
    retry_response, pass_plan = candidate(retry_request)
    pass_request = {"request_id": REQUEST_ID, "state": state, "plan": pass_plan}
    pass_response = call("validate_plan", pass_request)
    approval = pass_response["result"]
    if not approval["pass"] or not approval["power_flow"]["converged"]:
        raise RuntimeError(f"Expected an AC-safe replan: {pass_response}")

    # A separate deliberately unsafe plan; never modify or reuse an approved ID.
    bad_plan = {**pass_plan, "plan_id": "joint-unsafe-ess-over-limit",
                "battery_power_kw": min(state["battery_discharge_max_kw"],
                                        config.battery.discharge_max_kw) + 1.0}
    hard_request = {"request_id": REQUEST_ID, "state": state, "plan": bad_plan}
    hard_response = call("validate_plan", hard_request)
    hard = hard_response["result"]
    if (hard["pass"] or hard["power_flow"] is not None
            or "ESS_DISCHARGE_LIMIT" not in {r["code"] for r in hard["violated_rules"]}):
        raise RuntimeError(f"Expected hard-rule rejection: {hard_response}")
    if json.dumps(state, sort_keys=True) != before:
        raise RuntimeError("Optimization/validation must not mutate the snapshot")

    return {
        "metadata": {
            "kind": "offline-contract-fixtures", "runtime_base_commit": RUNTIME_BASE,
            "profile": "proposed-pv350to100-demand350-no-shed",
            "synthetic_state_not_c_telemetry": True, "not_execution_authorization": True,
            "config_fingerprint": fingerprint(config),
            "state_fingerprint": fingerprint(state_model), "python": platform.python_version(),
            "dependencies": {p: version(p) for p in ("pandapower", "scipy", "numpy", "pydantic")},
        },
        "config": config.wire(), "state": state,
        "c_telemetry_proposal": proposed_c_telemetry(state_model),
        "initial": {"optimize_request": first_request, "optimize_response": first_response,
                    "validate_request": reject_request, "validate_response": reject_response},
        "replan": {"optimize_request": retry_request, "optimize_response": retry_response,
                   "validate_request": pass_request, "validate_response": pass_response},
        "hard_reject": {"validate_request": hard_request, "validate_response": hard_response},
    }


def write_cases(output, bundle):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    files = {"bundle.json": bundle, "config.json": bundle["config"], "state.json": bundle["state"],
             "c-telemetry.proposed.json": bundle["c_telemetry_proposal"]}
    for section, prefix in (("initial", "reject-ac"), ("replan", "pass"), ("hard_reject", "reject-hard")):
        for key, value in bundle[section].items():
            files[f"{prefix}.{key.replace('_', '.')}.json"] = value
    for filename, data in files.items():
        (output / filename).write_text(
            json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/joint-pv-drop"))
    args = parser.parse_args(argv)
    bundle = build_cases()  # Only write a complete, actually verified fixture set.
    write_cases(args.output, bundle)
    print(json.dumps({"output": str(args.output), "ac_reject": True, "ac_pass": True,
                      "hard_reject": True, "device_commands_sent": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
