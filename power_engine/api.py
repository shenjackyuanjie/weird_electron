"""JSON-only internal adapter for future MCP/Backend integration; NOT an MCP server."""
from uuid import uuid4

from pydantic import ValidationError

from power_engine.contracts import EngineError, MicrogridConfig
from power_engine.optimizer import optimize_dispatch
from power_engine.power_flow import run_power_flow
from power_engine.validator import validate_plan


def invoke(tool: str, payload: dict, config: MicrogridConfig | None = None) -> dict:
    request_id = str(payload.get("request_id") or uuid4())
    try:
        allowed = {"state", "request_id", "duration_seconds", "feedback"} if tool == "optimize_dispatch" else {"state", "plan", "request_id"}
        if set(payload) - allowed:
            raise ValueError("Unknown top-level fields")
        if tool == "optimize_dispatch":
            result = optimize_dispatch(payload["state"], config,
                                       duration_seconds=payload.get("duration_seconds"), feedback=payload.get("feedback"))
        elif tool == "run_power_flow":
            result = run_power_flow(payload["state"], payload["plan"], config)
        elif tool == "validate_plan":
            result = validate_plan(payload["state"], payload["plan"], config)
        else:
            raise EngineError("UNKNOWN_TOOL", f"Unsupported tool: {tool}")
        if tool == "optimize_dispatch" and result.plan is not None:
            result = result.model_copy(update={
                "plan": result.plan.model_copy(update={"request_id": request_id})
            })
        return {"ok": True, "request_id": request_id, "result": result.wire()}
    except (ValidationError, ValueError, KeyError) as exc:
        return {"ok": False, "request_id": request_id, "error_code": "INVALID_INPUT", "message": str(exc)}
    except EngineError as exc:
        return {"ok": False, "request_id": request_id, "error_code": exc.code, "message": str(exc)}
