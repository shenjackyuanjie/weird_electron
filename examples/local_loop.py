"""Run normal -> fault A -> normal conditions using the real local controller.

From the repository root: python -m examples.local_loop
"""
import json

from power_engine.contracts import MicrogridConfig
from simulator.cli import run_episode


def run_demo(policy: str = "optimizer") -> dict:
    summary, trace = run_episode(MicrogridConfig(), "A", policy=policy, steps=6)
    if not summary["complete"]:
        raise RuntimeError(f"Episode did not complete: {summary}")
    if any(not entry["execution_audit"]["passed"] for entry in trace):
        raise RuntimeError("An executed interval failed its evidence audit")
    return summary


if __name__ == "__main__":
    print(json.dumps(run_demo(), indent=2, ensure_ascii=False, allow_nan=False))
