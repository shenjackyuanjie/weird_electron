"""Reproducible local demos and paired-seed experiments; JSONL traces plus CSV metrics."""
import argparse
import csv
import json
import random
import time
from pathlib import Path

from power_engine.contracts import (
    DispatchPlan, ExecutionReceipt, MicrogridConfig, MicrogridState, ValidationResult,
)
from simulator.controller import control_step
from simulator.scenarios import SCENARIOS
from simulator.simulator import MicrogridSimulator


def run_episode(config, scenario_id, *, policy="optimizer", steps=6, severity=None):
    if steps < 3:
        raise ValueError("At least three intervals are required: normal, fault, recovery")
    simulator = MicrogridSimulator(config)
    trace = []
    requested = delivered = pv_available = pv_used = 0.0
    rejected = violations = completed = 0
    for index in range(steps):
        if index == 1:
            simulator.trigger_scenario(scenario_id, severity)
        elif index == steps - 1:
            simulator.trigger_scenario("normal")
        start = time.perf_counter()
        result = control_step(simulator, policy)
        result["local_control_latency_ms"] = (time.perf_counter() - start) * 1000
        trace.append(result)
        rejected += sum(not a["validation"]["pass"] for a in result["attempts"])
        if not result["success"]:
            break  # Do not fabricate elapsed simulation time or served energy after a failure.
        completed += 1
        before, after = result["before"], result["state"]
        duration = result["attempts"][-1]["plan"]["duration_seconds"] / 3600
        requested += before["load_critical_kw"] * duration
        delivered += after["critical_served_kw"] * duration
        pv_available += before["pv_available_kw"] * duration
        pv_used += after["pv_power_kw"] * duration
        # Check observed execution boundaries separately from the candidate gate count.
        violations += int(not (
            config.battery.soc_min - 1e-10 <= after["battery_soc"] <= config.battery.soc_max + 1e-10
            and after["grid_power_kw"] <= before["grid_import_max_kw"] + 0.02
            and after["grid_power_kw"] >= -before["grid_export_max_kw"] - 0.02
            and after["critical_served_kw"] == before["load_critical_kw"]
        ))
    complete = completed == steps
    summary = {
        "scenario_id": scenario_id, "policy": policy, "complete": complete,
        "requested_intervals": steps, "completed_intervals": completed,
        "error_code": None if complete else trace[-1]["error_code"],
        "rejected_candidates": rejected, "executed_constraint_violations": violations,
        "critical_supply_ratio": delivered / requested if complete and requested else None,
        "pv_utilization_ratio": pv_used / pv_available if complete and pv_available else None,
        "final_soc": simulator.get_state().battery_soc,
        "max_local_control_latency_ms": max(t["local_control_latency_ms"] for t in trace),
    }
    return summary, trace


def write_episode(path, config, summary, trace):
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")
    (path / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (path / "trace.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in trace), encoding="utf-8")


def run_batch(output: Path, cases=40, steps=4):
    if not 1 <= cases <= 10000:
        raise ValueError("cases must be in [1, 10000]")
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for seed in range(cases):
        rng = random.Random(seed)
        cfg = MicrogridConfig(
            pv_available_kw=rng.uniform(220, 400), load_critical_kw=rng.uniform(180, 230),
            load_normal_kw=rng.uniform(200, 330), grid_import_max_kw=rng.uniform(50, 160),
            battery={"initial_soc": rng.uniform(0.10001, 0.85), "discharge_max_kw": rng.uniform(80, 220)},
        )
        scenario = ("A", "B", "C")[seed % 3]
        severity = rng.uniform(10, 100) if scenario == "A" else rng.uniform(5, 40)
        for policy in ("baseline", "optimizer"):
            summary, trace = run_episode(cfg, scenario, policy=policy, steps=steps, severity=severity)
            summary = {"seed": seed, "severity_kw": severity, **summary}
            rows.append(summary)
            write_episode(output / f"seed-{seed:03d}-{policy}", cfg, summary, trace)
    with (output / "results.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {"episodes": len(rows), "complete": sum(r["complete"] for r in rows),
            "incomplete": sum(not r["complete"] for r in rows),
            "executed_constraint_violations": sum(r["executed_constraint_violations"] for r in rows)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Run normal -> one fault -> recovery")
    demo.add_argument("--scenario", choices=SCENARIOS, default="A")
    demo.add_argument("--policy", choices=("optimizer", "baseline"), default="optimizer")
    demo.add_argument("--steps", type=int, default=6)
    demo.add_argument("--config", type=Path)
    demo.add_argument("--output", type=Path, default=Path("outputs/demo"))
    batch = sub.add_parser("batch", help="Run paired seeds; preserve failures, without fake Agent baselines")
    batch.add_argument("--cases", type=int, default=40)
    batch.add_argument("--steps", type=int, default=4)
    batch.add_argument("--output", type=Path, default=Path("outputs/batch"))
    schemas = sub.add_parser("schemas")
    schemas.add_argument("--output", type=Path, default=Path("outputs/schemas"))
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            cfg = MicrogridConfig.model_validate_json(args.config.read_text(encoding="utf-8")) if args.config else MicrogridConfig()
            summary, trace = run_episode(cfg, args.scenario, policy=args.policy, steps=args.steps)
            write_episode(args.output, cfg, summary, trace)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if summary["complete"] else 2
        if args.command == "batch":
            print(json.dumps(run_batch(args.output, args.cases, args.steps), indent=2))
            return 0  # Infeasible random cases are observations, not erased test failures.
        args.output.mkdir(parents=True, exist_ok=True)
        for cls in (MicrogridConfig, MicrogridState, DispatchPlan, ValidationResult, ExecutionReceipt):
            (args.output / f"{cls.__name__}.json").write_text(json.dumps(cls.model_json_schema(), indent=2), encoding="utf-8")
        print(f"Schemas written to {args.output}")
        return 0
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
