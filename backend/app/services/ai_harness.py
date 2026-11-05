"""Auditable AI-harness primitives for revenue reconciliation.

This first release is deliberately provider-independent: it creates structured,
evidence-grounded investigations from deterministic reconciliation results. It
never edits financial values, mappings, or approved rules.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import hashlib
import json

HARNESS_VERSION = "2.0.0-phase2-investigation-agent"

ROOT_CAUSES = {
    "SOURCE_COUNT_DIFFERENCE": ("Source population/count difference", ["Compare source period and cut-off", "Inspect missing/duplicate transaction references", "Verify BC reporting population and reversals"]),
    "BC_ONLY_ACTIVITY": ("BC-only activity", ["Determine whether the item is a supplemental commission or transaction", "Check whether the matching source was uploaded", "Confirm the applicable approved rule"]),
    "UNMAPPED": ("Unmapped transaction type", ["Compare raw descriptions against the approved mapping master", "Request mapping approval if product identity is not explicit"]),
    "RATE_MASTER_MISSING": ("Missing commission rule", ["Inspect the approved SBI rate/slab master", "Verify required eligibility evidence", "Do not estimate the rate from actual payout"]),
    "AMBIGUOUS_RATE_RULE": ("Ambiguous commission rule", ["Identify overlapping rules and their conditions", "Resolve through an approved rule change before settlement"]),
    "Shortfall": ("Potential commission shortfall", ["Compare expected and actual commission inputs", "Check slab, eligibility, cap, count and period", "Verify the actual amount directly against the BC report"]),
    "Excess": ("Potential commission excess", ["Compare expected and actual commission inputs", "Check duplicate rows, rate selection and caps", "Verify the actual amount directly against the BC report"]),
    "Missing Commission Pair": ("Missing BC commission pair", ["Check the CSP and transaction-type key", "Inspect source-period coverage", "Confirm whether the BC report omits the group"]),
    "EVIDENCE_REQUIRED": ("Eligibility evidence missing", ["Check which condition needs proof (for example e-KYC or OVD for account opening)", "Ask for the evidence before treating the group as final", "Do not assume the evidence from the amount alone"]),
    "MAPPING_PENDING": ("Mapping pending approval", ["Review supporting product evidence", "Obtain approval before treating the group as settlement-ready"]),
}


def _clean(v: Any) -> Any:
    try:
        import pandas as pd
        import numpy as np
        if v is None or v is pd.NA or v is pd.NaT: return None
        if isinstance(v, (np.integer,)): return int(v)
        if isinstance(v, (np.floating, float)): return float(v) if np.isfinite(v) else None
        if isinstance(v, (np.bool_,)): return bool(v)
        if pd.isna(v): return None
    except (ImportError, TypeError, ValueError):
        pass
    if isinstance(v, dict): return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [_clean(x) for x in v]
    if hasattr(v, "item"):
        try: return _clean(v.item())
        except Exception: pass
    return v


def _exception_frame(result):
    if result is None or not hasattr(result, "columns"):
        raise ValueError("No reconciliation result is available. Upload the current-period sources and run reconciliation first.")
    if "exception_flag" in result.columns:
        return result[result["exception_flag"].fillna(False).astype(bool)]
    return result


def _case_for(row):
    status = str(row.get("reconciliation_status", "UNKNOWN"))
    title, actions = ROOT_CAUSES.get(status, ("Reconciliation exception", ["Review source rows and the deterministic calculation trace", "Keep unresolved until supporting evidence is available"]))
    csp = _clean(row.get("csp_id")); tx_type = _clean(row.get("transaction_type"))
    identity = json.dumps([csp, tx_type, _clean(row.get("measurement_type"))], ensure_ascii=False, sort_keys=True)
    return {
        "case_id": "AIH-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12].upper(),
        "csp_id": csp, "transaction_type": tx_type, "status": status,
        "root_cause_hypothesis": title,
        "evidence": {k: _clean(row.get(k)) for k in ("successful_transactions", "report_base", "count_variance", "expected_commission", "actual_commission", "financial_gap", "settlement_rule_approved", "verified_expected_commission", "mismatch_reason") if k in row.index},
        "recommended_checks": actions,
        "decision": "INVESTIGATE", "approval_required": True,
        "financial_values_modified": False,
        "note": "Hypothesis only. Verify against source rows and approved SBI rules; this harness does not approve or alter financial calculations."
    }


def _report(result, exceptions, rows, metadata):
    metadata = metadata or {}
    source_signature = hashlib.sha256(json.dumps(_clean(metadata), sort_keys=True, default=str).encode()).hexdigest()
    counts = exceptions["reconciliation_status"].value_counts().to_dict() if len(exceptions) and "reconciliation_status" in exceptions else {}
    return {
        "harness_version": HARNESS_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "evidence-grounded-deterministic-investigation",
        "source_metadata_sha256": source_signature,
        "total_result_groups": int(len(result)),
        "exception_groups": int(len(exceptions)),
        "cases_returned": len(rows),
        "exception_status_counts": {str(k): int(v) for k, v in counts.items()},
        "cases": rows,
        "guardrails": ["No commission calculation performed by AI", "No rule or mapping automatically changed", "No fuzzy identity match auto-approved", "All proposed fixes require evidence and regression tests", "Financial values are read-only in this harness"],
    }


def investigate_result(result, metadata: dict | None = None, limit: int = 100) -> dict:
    """Produce auditable investigation cases from the current deterministic result."""
    exceptions = _exception_frame(result)
    rows = [_case_for(row) for _, row in exceptions.head(max(1, min(int(limit), 500))).iterrows()]
    return _report(result, exceptions, rows, metadata)


# Phase 2: deterministic investigation triage. Scores prioritize review only;
# they are not a probability, settlement decision, or financial adjustment.
STATUS_PRIORITY = {
    "RATE_MASTER_MISSING": 45, "AMBIGUOUS_RATE_RULE": 45, "UNMAPPED": 42, "EVIDENCE_REQUIRED": 36,
    "MAPPING_PENDING": 42, "Missing Commission Pair": 38, "Shortfall": 35,
    "Excess": 32, "SOURCE_COUNT_DIFFERENCE": 30, "BC_ONLY_ACTIVITY": 28,
}

def _number(row, key):
    try:
        value = row.get(key)
        if value is None: return 0.0
        value = float(value)
        return abs(value) if value == value and value not in (float("inf"), float("-inf")) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _triage_case(row, case):
    status = str(case.get("status") or "UNKNOWN")
    score = STATUS_PRIORITY.get(status, 20)
    reasons = []
    financial_gap = _number(row, "financial_gap")
    count_variance = _number(row, "count_variance")
    expected = _number(row, "expected_commission")
    actual = _number(row, "actual_commission")
    if status in ("RATE_MASTER_MISSING", "AMBIGUOUS_RATE_RULE", "UNMAPPED", "MAPPING_PENDING"):
        reasons.append("Rule or mapping uncertainty can affect settlement correctness")
    if financial_gap > 0:
        score += min(25, 5 + int(financial_gap ** 0.5))
        reasons.append("Non-zero financial variance is present")
    if count_variance > 0:
        score += min(15, 3 + int(count_variance ** 0.5))
        reasons.append("Source transaction count differs")
    if expected > 0 and actual == 0:
        score += 8
        reasons.append("Expected commission exists but actual commission is zero")
    approved = row.get("settlement_rule_approved")
    if approved is False or str(approved).strip().lower() in ("false", "0", "no"):
        score += 10
        reasons.append("Settlement rule is not approved")
    score = min(100, score)
    band = "P1 - URGENT" if score >= 70 else ("P2 - HIGH" if score >= 50 else ("P3 - NORMAL" if score >= 30 else "P4 - LOW"))
    case.update({
        "priority_score": score,
        "priority_band": band,
        "priority_reasons": reasons or ["Exception status requires source-level verification"],
        "cause_confidence": "RULE-BASED HYPOTHESIS",
        "financial_values_modified": False,
        "approval_required": True,
    })
    return case


def run_investigation_agent(result, metadata: dict | None = None, limit: int = 100) -> dict:
    """Phase 2 agent: rank EVERY exception, then return the `limit` most urgent (V62.6.216).

    Earlier the first `limit` rows of the table were taken and only those were ranked, so an urgent case further down the table
    never reached the queue."""
    exceptions = _exception_frame(result)
    ranked = []
    for _, row in exceptions.iterrows():
        ranked.append(_triage_case(row, _case_for(row)))
    ranked.sort(key=lambda c: (-int(c["priority_score"]), c["case_id"]))
    bands = ("P1 - URGENT", "P2 - HIGH", "P3 - NORMAL", "P4 - LOW")
    all_counts = {band: sum(1 for c in ranked if c["priority_band"] == band) for band in bands}
    ranked = ranked[:max(1, min(int(limit), 500))]
    for rank, case in enumerate(ranked, start=1):
        case["queue_rank"] = rank
    report = _report(result, exceptions, ranked, metadata)
    report["mode"] = "phase2-deterministic-investigation-agent"
    report["agent_summary"] = {
        "prioritization": "Deterministic rule-based ranking, not an LLM diagnosis",
        "queue_size": len(ranked),
        "priority_counts": {band: sum(1 for c in ranked if c["priority_band"] == band) for band in bands},
        "priority_counts_all_exceptions": all_counts,
        "queue_note": f"All {len(exceptions)} exceptions were ranked; the {len(ranked)} most urgent are returned.",
        "tool_contracts_available": ["validate_upload", "resolve_csp_identity", "calculate_expected_commission", "reconcile_period", "explain_variance", "calculate_kpi"],
        "tools_executed_automatically": [],
        "why_no_auto_execution": "Investigation does not automatically rerun reconciliation or mutate data; tools requiring scoped arguments remain user-invoked.",
    }
    report["guardrails"] = list(report.get("guardrails", [])) + [
        "Priority score is a review-order heuristic, not a probability or settlement verdict",
        "No LLM provider configured; all prioritization is deterministic",
        "No financial write operations are available to the agent",
    ]
    return report


# Phase 1: deterministic, read-only tools over the existing reconciliation engine.
# These are intentionally ordinary Python functions with a stable API contract;
# a future agent can call them without gaining write access to financial sources.
TOOL_CATALOG = [
    {"name": "validate_upload", "description": "Inspect current upload metadata, validation status, and source availability."},
    {"name": "resolve_csp_identity", "description": "Resolve an exact CSP ID/name using only the current-period authoritative BC identity crosswalk."},
    {"name": "calculate_expected_commission", "description": "Summarize deterministic expected-commission values from the current reconciliation result."},
    {"name": "reconcile_period", "description": "Run the existing deterministic reconciliation engine for the current uploaded period."},
    {"name": "explain_variance", "description": "Return source-backed variance evidence for a CSP and/or transaction type."},
    {"name": "calculate_kpi", "description": "Return the canonical dashboard KPI payload from the existing dashboard service."},
]


def _tool_json(value):
    return _clean(value)


def _current_result(force: bool = False):
    from app.api.reconciliation import load_result
    return load_result(force=force)


def _supplemental_metadata(upload_api, kind):
    import json
    names = [f"latest_{kind}_metadata.json"]
    for name in names:
        p = upload_api.SUPPLEMENTAL / name
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
    return {}


def _validate_upload(args: dict) -> dict:
    from pathlib import Path
    from app.services.upload_metadata import load_metadata
    from app.api import upload as upload_api
    meta = load_metadata()
    path_map = {
        "transactions": upload_api.TX / "latest_transactions.csv",
        "commission": upload_api.CM / "latest_commission.csv",
        "rate_master": upload_api.RM / "latest_rate_master.csv",
        "csp_geography": upload_api.GEO / "latest_csp_geography.csv",
        "rural_csp": upload_api.RURAL,
        "social_security_counts": upload_api.SOCIAL_COUNTS,
        "passbook_printing_counts": upload_api.PASSBOOK_COUNTS,
        "dfs_incentive": upload_api.DFS_COUNTS,
        "women_csp_roster": upload_api.WOMEN_COUNTS,
        "tab_incentive": upload_api.SUPPLEMENTAL / "latest_tab_incentive_counts.csv",
        "loan_lead_generation": upload_api.SUPPLEMENTAL / "latest_loan_lead_generation.csv",
        "matm_incentive": upload_api.SUPPLEMENTAL / "latest_matm_incentive_counts.csv",
    }
    requested = str(args.get("kind") or "").strip().lower()
    kinds = [requested] if requested else ["transactions", "commission", "rate_master"]
    unknown = [k for k in kinds if k not in path_map]
    if unknown:
        raise ValueError(f"Unsupported upload kind: {', '.join(unknown)}")
    results = []
    for kind in kinds:
        item = meta.get(kind) or {}
        path = Path(path_map[kind])
        exists = path.exists()
        own_file = False
        if not item and exists:                       # supplemental files keep their details in their own small metadata file
            item = _supplemental_metadata(upload_api, kind); own_file = bool(item)
        validation = item.get("validation") or ({"valid": True} if own_file else {})     # that file is only written after the upload passed its checks
        periods = item.get("periods") or []
        results.append({
            "kind": kind, "uploaded": bool(item) or exists, "file_exists": exists,
            "filename": item.get("filename"), "period_start": item.get("period_start") or (periods[0] if periods else None),
            "period_end": item.get("period_end"), "rows": item.get("rows", validation.get("rows")),
            "valid": bool(validation.get("valid")) if validation else False,
            "validation_status": validation.get("status") or ("VALID" if validation.get("valid") else "NOT_VALIDATED"),
            "errors": validation.get("errors", []), "sha256": item.get("sha256"),
        })
    return {"tool": "validate_upload", "read_only": True, "sources": results,
            "ready_for_reconciliation": all(x["uploaded"] and x["file_exists"] and x["valid"] for x in results if x["kind"] in ("transactions", "commission", "rate_master"))}


def _resolve_csp_identity(args: dict) -> dict:
    import pandas as pd
    from pathlib import Path
    from app.api.upload import CSP_IDENTITY, CSP_IDENTITY_META
    from app.services.upload_metadata import load_metadata
    csp_id = str(args.get("csp_id") or "").strip().upper()
    csp_name = " ".join(str(args.get("csp_name") or "").strip().upper().split())
    if not csp_id and not csp_name:
        raise ValueError("Provide csp_id or csp_name for identity lookup.")
    if not CSP_IDENTITY.exists():
        return {"tool": "resolve_csp_identity", "status": "NO_CURRENT_CROSSWALK", "resolved": False, "read_only": True}
    meta = load_metadata()
    cross_meta = {}
    try:
        import json
        cross_meta = json.loads(CSP_IDENTITY_META.read_text(encoding="utf-8")) if CSP_IDENTITY_META.exists() else {}
    except Exception:
        cross_meta = {}
    bc_meta = meta.get("commission") or {}
    # Never resolve against a stale crosswalk left by a different BC upload.
    if not cross_meta or cross_meta.get("sha256") != bc_meta.get("sha256") or cross_meta.get("batch_id") != bc_meta.get("batch_id"):
        return {"tool": "resolve_csp_identity", "status": "STALE_OR_UNBOUND_CROSSWALK", "resolved": False, "read_only": True}
    df = pd.read_csv(CSP_IDENTITY, dtype=str).fillna("")
    if "csp_id" not in df or "csp_name" not in df:
        return {"tool": "resolve_csp_identity", "status": "INVALID_CROSSWALK_SCHEMA", "resolved": False, "read_only": True}
    df["csp_id"] = df["csp_id"].astype(str).str.strip().str.upper()
    df["csp_name_norm"] = df["csp_name"].astype(str).str.strip().str.upper().str.split().str.join(" ")
    if csp_id:
        matches = df[df.csp_id.eq(csp_id)]
    else:
        matches = df[df.csp_name_norm.eq(csp_name)]
    ids = sorted(matches.csp_id.dropna().unique().tolist())
    names = sorted(matches.csp_name.dropna().unique().tolist())
    resolved = len(ids) == 1 and (not csp_id or ids[0] == csp_id)
    status = "RESOLVED_EXACT" if resolved else ("NOT_FOUND" if not ids else "AMBIGUOUS")
    return {"tool": "resolve_csp_identity", "status": status, "resolved": resolved,
            "csp_id": ids[0] if resolved else None, "matched_ids": ids, "matched_names": names,
            "crosswalk_period": cross_meta.get("period"), "read_only": True,
            "approval_required_for_any_manual_correction": True}


def _calculate_expected_commission(args: dict) -> dict:
    result = _current_result(force=False)
    import pandas as pd
    csp_filter = str(args.get("csp_id") or "").strip().upper()
    type_filter = str(args.get("transaction_type") or "").strip().upper()
    frame = result.copy()
    if csp_filter and "csp_id" in frame:
        frame = frame[frame.csp_id.astype(str).str.strip().str.upper().eq(csp_filter)]
    if type_filter and "transaction_type" in frame:
        frame = frame[frame.transaction_type.astype(str).str.strip().str.upper().eq(type_filter)]
    expected_col = "verified_expected_commission" if "verified_expected_commission" in frame.columns else "expected_commission"
    expected = pd.to_numeric(frame.get(expected_col, pd.Series(dtype=float)), errors="coerce")
    provisional = pd.to_numeric(frame.get("expected_commission", pd.Series(dtype=float)), errors="coerce")
    return {"tool": "calculate_expected_commission", "read_only": True,
            "filters": {"csp_id": csp_filter or None, "transaction_type": type_filter or None},
            "groups": int(len(frame)), "verified_expected_commission": float(expected.sum(min_count=1)) if expected.notna().any() else None,
            "calculated_expected_commission_including_provisional": float(provisional.sum(min_count=1)) if provisional.notna().any() else None,
            "groups_with_verified_expected": int(expected.notna().sum()),
            "groups_with_unverified_or_missing_expected": int(expected.isna().sum()),
            "note": "This tool reads the deterministic engine result; it does not infer rates from BC actuals or alter SBI rules."}


def _reconcile_period(args: dict) -> dict:
    result = _current_result(force=True)
    statuses = result["reconciliation_status"].value_counts(dropna=False).to_dict() if len(result) and "reconciliation_status" in result else {}
    matched = int((result["reconciliation_status"] == "MATCH").sum()) if len(result) and "reconciliation_status" in result else 0
    total = int(len(result))
    from app.api.dashboard import summary
    kpi = summary()
    return {"tool": "reconcile_period", "read_only": True, "status": "COMPLETED",
            "result_groups": total, "matched_groups": matched,
            "count_control_groups": kpi.get("count_control_groups"), "count_matched_groups": kpi.get("count_matched_groups"),
            "match_rate_percent": kpi.get("reconciliation_rate"),
            "status_counts": {str(k): int(v) for k, v in statuses.items()},
            "period_metadata": __import__("app.services.upload_metadata", fromlist=["load_metadata"]).load_metadata(),
            "note": "Executed the existing deterministic engine. The rate is the dashboard's own count-control rate (not a separate formula); matched_groups counts every result group with status MATCH. No rule, mapping, identity or financial value was changed."}


def _explain_variance(args: dict) -> dict:
    import pandas as pd
    csp = str(args.get("csp_id") or "").strip().upper()
    tx_type = str(args.get("transaction_type") or "").strip().upper()
    if not csp and not tx_type:
        raise ValueError("Provide csp_id and/or transaction_type to explain a variance.")
    result = _current_result(force=False)
    frame = result.copy()
    if csp and "csp_id" in frame:
        frame = frame[frame.csp_id.astype(str).str.strip().str.upper().eq(csp)]
    if tx_type and "transaction_type" in frame:
        frame = frame[frame.transaction_type.astype(str).str.strip().str.upper().eq(tx_type)]
    cols = [c for c in ("csp_id", "transaction_type", "reconciliation_status", "successful_transactions", "report_base", "count_variance", "expected_commission", "verified_expected_commission", "actual_commission", "actual_comparable_commission", "financial_gap", "financial_gap_status", "settlement_rule_approved", "mapping_confidence", "mismatch_reason") if c in frame.columns]
    rows = frame[cols].head(max(1, min(int(args.get("limit", 100)), 500))).to_dict(orient="records")
    return {"tool": "explain_variance", "read_only": True, "filters": {"csp_id": csp or None, "transaction_type": tx_type or None},
            "matched_groups_found": int(len(frame)), "evidence_rows_returned": len(rows), "evidence": _tool_json(rows),
            "note": "Evidence only. A variance hypothesis is not proof; no automatic mapping or financial correction is performed."}


def _calculate_kpi(args: dict) -> dict:
    from app.api.dashboard import summary
    payload = summary()
    # Return canonical backend KPI fields rather than independently recalculating in the harness.
    keep = ["reconciliation_rate", "count_matched_groups", "count_control_groups", "overall_controlled_reconciliation_rate",
            "overall_controlled_matched_groups", "overall_controlled_groups", "all_source_control_rate",
            "all_source_control_matched_groups", "all_source_control_groups",
            "dfs_control_matched_groups", "dfs_control_groups", "women_csp_matched_controls", "women_csp_control_groups",
            "matm_incentive_matched_controls", "matm_incentive_control_groups", "social_security_matched_controls", "social_security_control_groups",
            "tab_incentive_matched_controls", "tab_incentive_control_groups", "rural_commission_matched_controls", "rural_commission_control_groups"]
    missing = [k for k in keep if k not in payload]
    return {"tool": "calculate_kpi", "read_only": True, "kpis": {k: _tool_json(payload.get(k)) for k in keep if k in payload}, "not_available": missing,
            "note": "Canonical dashboard summary fields are reused. No separate AI-side KPI formula is introduced."}


def run_tool(name: str, args: dict | None = None) -> dict:
    """Execute one allow-listed, read-only Phase 1 harness tool."""
    args = args or {}
    tools = {
        "validate_upload": _validate_upload,
        "resolve_csp_identity": _resolve_csp_identity,
        "calculate_expected_commission": _calculate_expected_commission,
        "reconcile_period": _reconcile_period,
        "explain_variance": _explain_variance,
        "calculate_kpi": _calculate_kpi,
    }
    if name not in tools:
        raise ValueError(f"Unknown tool '{name}'. Allowed tools: {', '.join(tools)}")
    return _tool_json(tools[name](args))
