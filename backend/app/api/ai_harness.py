from fastapi import APIRouter, HTTPException, Query, Body
from app.api.reconciliation import load_result, _signature
from app.services.upload_metadata import load_metadata
from app.services.ai_harness import investigate_result, run_investigation_agent, HARNESS_VERSION, TOOL_CATALOG, run_tool

router = APIRouter()

@router.get('/status')
def harness_status():
    return {"enabled": True, "version": HARNESS_VERSION, "mode": "evidence-grounded-deterministic-investigation", "llm_provider_configured": False, "financial_write_access": False, "message": "Investigation tools are available. LLM-based reasoning is not configured; no financial values or rules are changed by this service."}

@router.post('/investigate')
def investigate(limit: int = Query(100, ge=1, le=500)):
    try:
        result = load_result()
        metadata = {"uploads": load_metadata(), "input_signature": _signature()}
        return run_investigation_agent(result, metadata, limit=limit)
    except FileNotFoundError:
        raise HTTPException(409, "No current reconciliation result. Upload current-period files and run reconciliation first.")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Harness investigation failed safely: {type(exc).__name__}: {exc}")


@router.post('/triage')
def triage(limit: int = Query(100, ge=1, le=500)):
    """Prioritize current exceptions for human investigation; never applies fixes."""
    try:
        result = load_result()
        metadata = {"uploads": load_metadata(), "input_signature": _signature()}
        return run_investigation_agent(result, metadata, limit=limit)
    except FileNotFoundError:
        raise HTTPException(409, "No current reconciliation result. Upload current-period files and run reconciliation first.")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Investigation triage failed safely: {type(exc).__name__}: {exc}")


@router.get('/tools')
def list_tools():
    return {"version": HARNESS_VERSION, "tools": TOOL_CATALOG, "mode": "read-only deterministic tools", "financial_write_access": False}

@router.post('/tools/{tool_name}')
def execute_tool(tool_name: str, payload: dict = Body(default={} )):
    try:
        return run_tool(tool_name, payload)
    except FileNotFoundError:
        raise HTTPException(409, "Current-period source/result is unavailable. Upload sources and run reconciliation first.")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(409, f"Tool could not complete safely: {type(exc).__name__}: {exc}")
