"""JSON-only internal adapter for future MCP/Backend integration; NOT an MCP server."""
from uuid import uuid4

from pydantic import ValidationError

from power_engine.contracts import (
    IDENTIFIER_ADAPTER, DispatchPlan, EngineError, MicrogridConfig, checked,
)
from power_engine.optimizer import optimize_dispatch
from power_engine.power_flow import run_power_flow
from power_engine.validator import validate_plan


def invoke(tool: str, payload: object, config: MicrogridConfig | None = None) -> dict:
    request_id = str(uuid4())
    try:
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object")
        if "request_id" in payload:
            request_id = IDENTIFIER_ADAPTER.validate_python(payload["request_id"])
        if not isinstance(tool, str):
            raise ValueError("Tool name must be a string")
        if tool not in ("optimize_dispatch", "run_power_flow", "validate_plan"):
            raise EngineError("UNKNOWN_TOOL", f"Unsupported tool: {tool}")
        allowed = {"state", "request_id", "duration_seconds", "feedback"} if tool == "optimize_dispatch" else {"state", "plan", "request_id"}
        if set(payload) - allowed:
            raise ValueError("Unknown top-level fields")
        if tool == "optimize_dispatch":
            result = optimize_dispatch(payload["state"], config,
                                       duration_seconds=payload.get("duration_seconds"),
                                       feedback=payload.get("feedback"))
            if result.plan is not None:
                result = result.model_copy(update={
                    "plan": result.plan.model_copy(update={"request_id": request_id})
                })
        else:
            plan = checked(DispatchPlan, payload["plan"])
            if "request_id" in payload and request_id != plan.request_id:
                raise ValueError("request_id must match plan.request_id")
            request_id = plan.request_id
            if tool == "run_power_flow":
                result = run_power_flow(payload["state"], plan, config)
            else:
                result = validate_plan(payload["state"], plan, config)
        return {"ok": True, "request_id": request_id, "result": result.wire()}
    except (ValidationError, ValueError, KeyError) as exc:
        return {"ok": False, "request_id": request_id, "error_code": "INVALID_INPUT", "message": str(exc)}
    except EngineError as exc:
        return {"ok": False, "request_id": request_id, "error_code": exc.code, "message": str(exc)}
