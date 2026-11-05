from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from app.platform_security import current_user, record_audit
from app.services import platform_jobs

router = APIRouter()
class JobRequest(BaseModel):
    job_type: str = Field(pattern=r"^(file_validation|reconciliation|report_export)$")
    payload: dict = Field(default_factory=dict)

@router.post("", status_code=202)
def submit_job(body: JobRequest, request: Request):
    actor = current_user(request)
    if actor.get("role") not in {"super_admin", "org_admin", "operator"}:
        raise HTTPException(status_code=403, detail="Viewer role cannot submit jobs.")
    org_id = actor.get("org")
    if not org_id and actor.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="User has no assigned organisation.")
    if not org_id:
        org_id = str(body.payload.get("organization_id", "")).strip()
        if not org_id: raise HTTPException(status_code=422, detail="Super admin must provide payload.organization_id.")
    # Payload is only queued, not executed by this API. A tenant-aware worker must
    # validate referenced uploads and execute allowed job types in a future deployment phase.
    job = platform_jobs.enqueue(org_id, actor["sub"], body.job_type, body.payload)
    record_audit(actor, "job.queued", {"job_id": job["id"], "job_type": body.job_type, "organization_id": org_id})
    return job

@router.get("")
def get_jobs(request: Request, limit: int = 50):
    actor = current_user(request)
    if actor.get("role") == "super_admin":
        org_id = request.query_params.get("organization_id", "").strip()
        if not org_id: raise HTTPException(status_code=422, detail="Super admin must specify organization_id.")
    else: org_id = actor.get("org")
    if not org_id: return {"items": []}
    return {"items": platform_jobs.list_jobs(org_id, limit)}

@router.get("/{job_id}")
def job_status(job_id: str, request: Request):
    actor = current_user(request)
    org_id = request.query_params.get("organization_id", "").strip() if actor.get("role") == "super_admin" else actor.get("org")
    if not org_id: raise HTTPException(status_code=422, detail="Organisation context is required.")
    job = platform_jobs.get_job(job_id, org_id)
    if not job: raise HTTPException(status_code=404, detail="Job not found in this organisation.")
    return job
