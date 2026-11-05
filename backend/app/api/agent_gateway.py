"""Minimal scoped agent gateway; read-only capability discovery, no financial writes."""
from fastapi import APIRouter, Header, HTTPException, Query
from app.platform_security import verify_scoped_api_key
router = APIRouter()

@router.get("/capabilities")
def capabilities(x_api_key: str = Header(default="", alias="X-API-Key"), organization_id: str = Query(..., min_length=2, max_length=64)):
    principal = verify_scoped_api_key(x_api_key, "audit:read", organization_id)
    return {"organization_id": principal["organization_id"], "capabilities": [
        {"name": "audit.read", "scope": "audit:read", "mode": "read-only"},
        {"name": "reconciliation.read", "scope": "reconciliation:read", "mode": "read-only; data API integration pending"}
    ], "note": "Gateway authentication and scope checks are active; business-data adapters must be connected before this agent can access reconciliation records."}
