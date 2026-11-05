from pathlib import Path
from io import BytesIO
import pandas as pd
from fastapi import APIRouter,HTTPException,Query,Request
from fastapi.responses import StreamingResponse
from app.services.reconciliation_engine import reconcile_transactions,aggregate_by_csp,aggregate_by_transaction_type,aggregate_by_csp_and_type,aggregate_social_security_reconciliation,reconcile_social_security_direct,build_condition_audit,TYPE_MAPPING,norm,map_transaction,load_passbook_printing_counts,load_social_security_counts,_single_calendar_month_from_transactions,_transaction_months_from_transactions,_period_month
from app.services.commission_engine import add_expected_commission
from app.services.transaction_processor import get_successful_transactions, load_successful_transactions
from app.services.exception_engine import build_exceptions
from app.services.upload_metadata import load_metadata
from app.services.audit_service import create_run_record
from app.services.reconciliation_cache import signature_from_metadata, read_cached, get_or_compute
from app.services.time_reconciliation import time_reconciliation
from app.services.rural_commission import load_rural_master, load_txn_mapping, reconcile_rural_commission, RURAL_MASTER_PATH
from app.services.result_memo import memo_on_files
router=APIRouter(); BASE_DIR=Path(__file__).resolve().parents[1]
GEO=BASE_DIR/'data'/'csp_geography'/'latest_csp_geography.csv'
AUDIT=BASE_DIR/'data'/'audit'/'latest_condition_audit.csv'
AUDIT_SUMMARY=BASE_DIR/'data'/'audit'/'latest_condition_summary.json'
AUDIT.parent.mkdir(parents=True,exist_ok=True)
TX=BASE_DIR/'data'/'transactions'/'latest_transactions.csv'; CM=BASE_DIR/'data'/'commissions'/'latest_commission.csv'; RM=BASE_DIR/'data'/'rate_master'/'latest_rate_master.csv'; SS=BASE_DIR/'data'/'supplemental'/'latest_social_security_counts.csv'
MATM=BASE_DIR/'data'/'supplemental'/'latest_matm_incentive_counts.csv'; MATM_META=BASE_DIR/'data'/'supplemental'/'latest_matm_incentive_metadata.json'; PB=BASE_DIR/'data'/'supplemental'/'latest_passbook_printing_counts.csv'; PBR=BASE_DIR/'data'/'supplemental'/'latest_passbook_printing_reconciliation.csv'; RURAL=RURAL_MASTER_PATH

def _signature():
    """Fingerprint every input/configuration that can affect reconciliation.

    Upload handlers clear the cache, but the signature is also the safety net for
    manual file replacement, interrupted uploads, and edits to permanent mapping
    masters. Use content hashes rather than size/mtime alone to avoid stale results
    when files are replaced while preserving timestamps.
    """
    import hashlib
    meta = load_metadata()
    sig = signature_from_metadata(meta, TX, CM, RM, GEO)
    data_dir = BASE_DIR / 'data'
    inputs = {
        'social_security_counts': SS,
        'matm_incentive_counts': MATM,
        'matm_incentive_metadata': MATM_META,
        'passbook_printing_counts': PB,
        'passbook_printing_exceptions': BASE_DIR / 'data' / 'supplemental' / 'latest_passbook_printing_count_exceptions.csv',
        'passbook_printing_reconciliation': PBR,
        'rural_csp': RURAL,
        'rural_transaction_type_mapping': data_dir / 'rural_csp' / 'rural_transaction_type_mapping.csv',
        'transaction_type_mapping_master': data_dir / 'transaction_type_mapping_master.csv',
        'approved_rule_master_reference': data_dir / 'rate_master' / 'approved_rule_master_reference.csv',
        'dfs_incentive_counts': data_dir / 'supplemental' / 'latest_dfs_incentive_counts.csv',
        'dfs_incentive_metadata': data_dir / 'supplemental' / 'latest_dfs_incentive_metadata.json',
        'women_csp_roster': data_dir / 'supplemental' / 'latest_women_csp_roster.csv',
        'women_csp_roster_metadata': data_dir / 'supplemental' / 'latest_women_csp_roster_metadata.json',
        'csp_identity_crosswalk': data_dir / 'supplemental' / 'latest_csp_identity_crosswalk.csv',
        'tab_incentive_counts': data_dir / 'supplemental' / 'latest_tab_incentive_counts.csv',
        'tab_incentive_metadata': data_dir / 'supplemental' / 'latest_tab_incentive_metadata.json',
        'loan_lead_generation': data_dir / 'supplemental' / 'latest_loan_lead_generation.csv',
        'loan_lead_generation_metadata': data_dir / 'supplemental' / 'latest_loan_lead_generation_metadata.json',
    }
    for key, path in inputs.items():
        if path.exists() and path.is_file():
            digest_obj = hashlib.sha256()
            with path.open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    digest_obj.update(chunk)
            digest = digest_obj.hexdigest()
            sig[key] = digest
        else:
            sig[key] = None
    for kind in ('transactions', 'commission', 'rate_master', 'csp_geography', 'rural_csp',
                 'social_security_counts', 'passbook_printing_counts', 'dfs_incentive',
                 'women_csp_roster', 'tab_incentive', 'loan_lead_generation', 'expected_commission_rule'):
        item = meta.get(kind) or {}
        sig[f'metadata_{kind}'] = {
            'sha256': item.get('sha256'),
            'batch_id': item.get('batch_id'),
            'period_start': item.get('period_start'),
            'period_end': item.get('period_end'),
        }
    return sig

def _compute_result():
    rules=pd.read_csv(RM,low_memory=False) if RM.exists() else None
    tx=load_successful_transactions(TX)
    cm=pd.read_csv(CM,low_memory=False)
    if 'channel' not in tx.columns:
        geo=None
        if GEO.exists():
            geo=pd.read_csv(GEO)
        elif 'channel' in cm.columns:
            geo=cm[['csp_id','channel']].copy()
        if geo is not None and 'channel' in geo.columns:
            geo['csp_id']=geo['csp_id'].astype('string').str.strip().str.upper()
            geo['channel']=geo['channel'].astype('string').str.strip().str.upper()
            geo=geo[geo['channel'].isin(['RURAL','URBAN'])].drop_duplicates('csp_id')
            tx['csp_id']=tx['csp_id'].astype('string').str.strip().str.upper()
            tx=tx.merge(geo,on='csp_id',how='left')
    # Supplemental CSP-wise controls are period-bound. A bundled historical
    # supplement must never leak into a different uploaded month.
    transaction_months = _transaction_months_from_transactions(tx)
    transaction_month = transaction_months[0] if len(transaction_months) == 1 else None
    # Keep only source rows whose explicit periods belong to this transaction run.
    # Multi-month files can reconcile when their supplements cover those same months;
    # old August-only rows cannot silently leak into a September/October run.
    social_security = load_social_security_counts()
    if not social_security.empty and transaction_months:
        social_security = social_security[social_security["period"].map(_period_month).isin(transaction_months)].copy()
    else:
        social_security = social_security.iloc[0:0].copy()
    passbook_printing = load_passbook_printing_counts()
    if not passbook_printing.empty and transaction_months:
        passbook_printing = passbook_printing[passbook_printing["period"].map(_period_month).isin(transaction_months)].copy()
    else:
        passbook_printing = passbook_printing.iloc[0:0].copy()
    result=reconcile_transactions(tx,cm,rules,social_security_counts=social_security,passbook_printing_counts=passbook_printing)
    # Build a row-level SBI condition audit from the same normalized source population
    # used by reconciliation. This is an audit/control artifact, not a second source.
    try:
        audit=build_condition_audit(tx,rules,cm) if rules is not None else pd.DataFrame()
        if not audit.empty:
            audit.to_csv(AUDIT,index=False)
            counts=audit['condition_status'].value_counts().to_dict()
            import json
            AUDIT_SUMMARY.write_text(json.dumps({
                'total_transactions':int(len(audit)),
                'ok':int(counts.get('OK',0)),
                'conditional':int(counts.get('CONDITIONAL',0)),
                'condition_fail':int(counts.get('CONDITION FAIL',0)),
                'unmapped':int(counts.get('UNMAPPED',0)),
                'verified_expected_commission':float(pd.to_numeric(audit.get('verified_expected_commission'),errors='coerce').sum(min_count=1) or 0),
                'provisional_expected_commission':float(pd.to_numeric(audit.get('provisional_expected_commission'),errors='coerce').sum(min_count=1) or 0)
            },indent=2))
    except Exception:
        # The financial reconciliation result remains authoritative; an audit artifact
        # failure must never turn a valid reconciliation into a false financial error.
        pass
    return result

def _source_quality_errors(meta):
    errors=[]
    tx=meta.get('transactions') or {}; cm=meta.get('commission') or {}; rm=meta.get('rate_master') or {}
    tv=tx.get('validation') or {}; cv=cm.get('validation') or {}; rv=rm.get('validation') or {}
    if not tv.get('valid',False): errors.append('Transaction source validation is not valid.')
    if not cv.get('valid',False): errors.append('Commission source validation is not valid.')
    if not rv.get('valid',False): errors.append('Rate/slab master validation is not valid.')
    if int(tv.get('invalid_success_rows',0) or 0)>0: errors.append(f"{int(tv.get('invalid_success_rows'))} successful transaction row(s) have invalid mandatory financial fields.")
    if int(tv.get('duplicate_successful_transaction_ids',0) or 0)>0: errors.append(f"{int(tv.get('duplicate_successful_transaction_ids'))} successful transaction row(s) have duplicate reference numbers; reconciliation is blocked until the successful duplicate population is resolved.")
    if int(tv.get('negative_success_amount_rows',0) or 0)>0: errors.append(f"{int(tv.get('negative_success_amount_rows'))} successful transaction row(s) have negative amounts; reversal/refund treatment must be explicitly approved before financial reconciliation.")
    if int(cv.get('invalid_commission_values',0) or 0)>0: errors.append(f"{int(cv.get('invalid_commission_values'))} commission row(s) have invalid actual commission values.")
    if rv.get('errors'): errors.extend([str(x) for x in rv.get('errors',[])])
    return errors

def _period_coverage_problem(ts, te, cs, ce):
    """Return a source-period problem when commission does not cover transactions."""
    if not all([ts, te, cs, ce]):
        return None
    if te < cs or ce < ts:
        return f'Source period mismatch: transaction period {ts} to {te} does not overlap commission period {cs} to {ce}.'
    if cs > ts or ce < te:
        return f'Incomplete commission-period coverage: transaction period {ts} to {te} is not fully covered by commission period {cs} to {ce}. Upload a BC commission report covering the full transaction period.'
    return None


def _transaction_and_commission_batch_problem(tx_meta, cm_meta):
    """Only period-specific transaction and BC commission files must share a batch.

    The approved SBI rate master is a permanent rule source. Requiring its metadata
    batch ID to equal each new monthly upload forced users to re-upload the rules
    every month and made a clean-start release unusable with its bundled rule master.
    """
    if not tx_meta or not cm_meta:
        return 'Transaction and commission sources must both be uploaded.'
    if not tx_meta.get('batch_id') or tx_meta.get('batch_id') != cm_meta.get('batch_id'):
        return 'Transaction and commission files are from different upload batches. Upload the two current-period sources together.'
    return None


def _require_sources():
    meta=load_metadata()
    if not TX.exists() or not CM.exists() or not RM.exists():
        raise HTTPException(400,'Upload and validate current-period transaction and commission files; an approved permanent rate/slab master must also be configured.')
    tx_meta,cm_meta,rm_meta=meta.get('transactions'),meta.get('commission'),meta.get('rate_master')
    if not tx_meta or not cm_meta or not rm_meta:
        raise HTTPException(400,'Current transaction and commission files plus a validated approved rate/slab master are required.')
    batch_problem=_transaction_and_commission_batch_problem(tx_meta,cm_meta)
    if batch_problem:
        raise HTTPException(400,batch_problem)
    quality=_source_quality_errors(meta)
    if quality:
        raise HTTPException(400,'Financial reconciliation blocked by source-control checks: ' + ' | '.join(quality))
    ts,te=tx_meta.get('period_start'),tx_meta.get('period_end'); cs,ce=cm_meta.get('period_start'),cm_meta.get('period_end')
    # Overlap alone is not sufficient for financial reconciliation: a commission
    # report that covers only part of the successful-transaction period could
    # otherwise silently omit expected/actual controls. Require the commission
    # source window to cover the entire transaction window whenever both windows
    # are known. If period metadata is unavailable, source validation must surface it.
    period_problem = _period_coverage_problem(ts,te,cs,ce)
    if period_problem:
        raise HTTPException(400,period_problem)
    return meta

def load_result(force=False):
    _require_sources()
    sig=_signature()
    if not force:
        cached=read_cached(sig)
        if cached is not None: return cached
    result,_=get_or_compute(sig,_compute_result)
    return result

@router.get('/rural-commission')
def rural_commission():
    meta=load_metadata()
    tx_meta=meta.get('transactions') or {}
    transaction_month=None
    transaction_months=[]
    if TX.exists():
        try:
            tx=load_successful_transactions(TX)
            if 'transaction_date' in tx.columns:
                from app.services.number_parser import parse_date_series
                parsed=parse_date_series(tx['transaction_date']).dropna()
                transaction_months=sorted(parsed.dt.to_period('M').astype(str).unique().tolist())
            transaction_month=_single_calendar_month_from_transactions(tx)
        except Exception:
            transaction_month=None
            transaction_months=[]
    if len(transaction_months)>1:
        return {'available':False,'status':'MULTI_PERIOD_UNSUPPORTED','message':f'Rural Commission is a monthly incentive. Uploaded successful transactions span {", ".join(transaction_months)}. Run the Rural Commission control separately for one calendar month with its matching Rural CSP login-day source.','summary':{'transaction_periods':transaction_months},'rows':[]}
    if not RURAL.exists():
        return {'available':False,'status':'RURAL_CSP_SOURCE_REQUIRED','message':'Upload the current-period Rural CSP list with Total Login Day (<month>).','summary':{},'rows':[]}
    try:
        cm=pd.read_csv(CM,low_memory=False) if CM.exists() else pd.DataFrame()
        return _json_safe_rural(reconcile_rural_commission(cm,transaction_month=transaction_month))
    except Exception as exc:
        return {'available':False,'status':'ERROR','message':str(exc),'summary':{},'rows':[]}

def _json_safe_rural(value):
    import math, numpy as np
    if value is None: return None
    if isinstance(value,float): return None if not math.isfinite(value) else value
    if isinstance(value,(int,bool,str)): return value
    if isinstance(value,(np.integer,np.floating)): return _json_safe_rural(value.item())
    if isinstance(value,dict): return {str(k):_json_safe_rural(v) for k,v in value.items()}
    if isinstance(value,list): return [_json_safe_rural(v) for v in value]
    try:
        if pd.isna(value): return None
    except Exception: pass
    return value

@router.get('/status')
def reconciliation_status():
    meta=load_metadata()
    paths={'transactions':TX,'commission':CM,'rate_master':RM,'csp_geography':GEO,'rural_csp':RURAL}
    upload_attempt_errors=meta.get('upload_attempt_errors') or {}
    sources={}
    for kind,path in paths.items():
        item=meta.get(kind) or {}
        validation=item.get('validation') or {}
        # Source status means usable/validated, not merely that an old normalized
        # file happens to exist on disk. A failed upload attempt blocks the source.
        sources[kind]=bool(item and path.exists() and validation.get('valid', True) and kind not in upload_attempt_errors)
    tx_meta=meta.get('transactions') or {}; cm_meta=meta.get('commission') or {}; rm_meta=meta.get('rate_master') or {}
    same_batch=_transaction_and_commission_batch_problem(meta.get('transactions'),meta.get('commission')) is None

    quality_errors=[]
    readiness_errors=[]
    required_files_present=all((meta.get(k) and paths[k].exists()) for k in ('transactions','commission','rate_master'))
    for kind,label in (('transactions','current-period Successful Transaction file'),('commission','matching current-period BC Commission file'),('rate_master','permanent approved SBI rate/slab master')):
        if not meta.get(kind) or not paths[kind].exists():
            readiness_errors.append(f'Missing {label}.')
    if required_files_present:
        quality_errors=_source_quality_errors(meta)
        readiness_errors.extend(quality_errors)
    for kind in ('transactions','commission'):
        failed=upload_attempt_errors.get(kind)
        if failed:
            fname=failed.get('filename') or kind
            msg=failed.get('message') or 'upload failed'
            readiness_errors.append(f'Latest {kind} upload attempt ({fname}) failed; previous source is preserved but reconciliation is blocked until a valid replacement is uploaded. Details: {msg}')
    batch_problem=_transaction_and_commission_batch_problem(meta.get('transactions'),meta.get('commission'))
    if batch_problem:
        readiness_errors.append(batch_problem)

    tx_start,tx_end=tx_meta.get('period_start'),tx_meta.get('period_end')
    cm_start,cm_end=cm_meta.get('period_start'),cm_meta.get('period_end')
    period_overlap=True
    if all([tx_start,tx_end,cm_start,cm_end]):
        period_overlap=not (tx_end < cm_start or cm_end < tx_start)
    period_coverage_problem=_period_coverage_problem(tx_start,tx_end,cm_start,cm_end)
    if period_coverage_problem:
        readiness_errors.append(period_coverage_problem)

    ready=required_files_present and all(sources[k] for k in ('transactions','commission','rate_master')) and not readiness_errors
    cached=read_cached(_signature()) if ready else None
    return {'sources':sources,'same_batch':same_batch,'period_overlap':period_overlap,
            'period_coverage_ok':period_coverage_problem is None,
            'period_coverage_problem':period_coverage_problem,
            'quality_errors':quality_errors,'readiness_errors':readiness_errors,
            'upload_attempt_errors':upload_attempt_errors,
            'ready_to_run':ready,'reconciliation_cached':cached is not None,
            'upload_sources':meta,'rural_commission_source_required_for_control':True,
            'rural_commission_source_period':(meta.get('rural_csp') or {}).get('period')}

def rec(df):
    clean=df.copy().replace([float('inf'),float('-inf')],pd.NA)
    clean=clean.astype(object).where(pd.notnull(clean),None)
    return clean.to_dict(orient='records')

@router.post('/run')
def run(request: Request = None):
    # Reuse the deterministic result when every source hash and the engine version
    # are unchanged. Upload endpoints invalidate the cache whenever a source changes.
    cache_hit = read_cached(_signature()) is not None
    r=load_result(force=False)
    meta=load_metadata()
    record=create_run_record(TX, CM, RM, meta, r)
    # `total_successful_transactions` is the uploaded Success-file KPI. The
    # CSP-wise PMJJBY/PMSBY supplement is an additional reconciliation control
    # population and is reported separately so it can never inflate the source KPI.
    try:
        tx_meta = (meta.get('transactions') or {})
        validation = tx_meta.get('validation') or {}
        # Validation metadata is generated during upload and avoids rereading the
        # 38 MB normalized transaction CSV solely to display its source-row KPI.
        source_success_count = int(validation.get('processable_rows') or validation.get('rows') or 0)
        if not source_success_count:
            source_success_count = int(r.loc[~r.get('is_supplemental', pd.Series(False, index=r.index)).fillna(False), 'successful_transactions'].sum())
    except Exception:
        source_success_count = int(r.loc[~r.get('is_supplemental', pd.Series(False, index=r.index)).fillna(False), 'successful_transactions'].sum())
    from app.services.control_population import summarize_control_population
    population_counts = summarize_control_population(r)
    # Save the month automatically (snapshot + its source files in the database), whoever ran it.
    try:
        from app.api.reconciliation_history import archive_current_reconciliation
        month = archive_current_reconciliation(request)
    except HTTPException as exc:
        month = {'saved': False, 'error': exc.detail}
    except Exception as exc:
        month = {'saved': False, 'error': f'{type(exc).__name__}: {exc}'}
    return {'message':'Reconciliation completed','cached_result': cache_hit,'run_id':record['run_id'],'month_saved':month,'total_successful_transactions':source_success_count,
            **population_counts, 'rate_master_configured':RM.exists(),'exception_groups':record['exception_groups'],
            'expected_commission':record['expected_commission'],'actual_commission':record['actual_commission'],'variance':record['variance']}
@router.get('/csp')
def csp(): return rec(aggregate_by_csp(load_result()))
@router.get('/social-security')
@memo_on_files(lambda:[SS,CM,TX])
def social_security():
    # PMJJBY/PMSBY is a separate CSP-wise settlement control. It must not disappear
    # merely because the unrelated core Success file spans another period, has no SSS
    # rows, or the general rate-master batch is not ready. Match the scheme source
    # directly to the currently uploaded BC commission report, with strict period guard.
    if not CM.exists():
        return {"available":False,"status":"COMMISSION_SOURCE_REQUIRED","message":"Upload the matching-period BC commission report first.","schemes":[],"rows":[],"total":{}}
    source=load_social_security_counts()
    if source.empty:
        return {"available":False,"status":"SOCIAL_SECURITY_SOURCE_REQUIRED","message":"Upload the current-period PMJJBY/PMSBY CSP-wise source workbook.","schemes":[],"rows":[],"total":{}}
    meta=load_metadata(); cm_meta=meta.get('commission') or {}; ss_meta=meta.get('social_security_counts') or {}
    source_periods=sorted(set(source.get('period',pd.Series(dtype=str)).map(_period_month).dropna().tolist()))
    cs,ce=cm_meta.get('period_start'),cm_meta.get('period_end')
    if cs and ce and source_periods:
        from app.services.reconciliation_engine import _period_month as norm_month
        cm_periods=set(pd.period_range(pd.Timestamp(cs),pd.Timestamp(ce),freq='M').astype(str).tolist())
        if not set(source_periods).issubset(cm_periods):
            return {"available":False,"status":"PERIOD_MISMATCH","message":f"PMJJBY/PMSBY source period {', '.join(source_periods)} does not match BC report period {cs} to {ce}.","source_periods":source_periods,"schemes":[],"rows":[],"total":{}}
    commission=pd.read_csv(CM,low_memory=False)
    out=reconcile_social_security_direct(source,commission,period=source_periods[0] if len(source_periods)==1 else None)
    out['source_file']=(ss_meta.get('filename') or 'Uploaded PMJJBY/PMSBY source')
    out['commission_file']=(cm_meta.get('filename') or 'Uploaded BC commission report')
    out['source_periods']=source_periods
    out['source_data_quality']=__import__('app.services.reconciliation_engine',fromlist=['load_social_security_count_exceptions']).load_social_security_count_exceptions(transaction_months=source_periods)
    # Keep full-source totals visible without falsely allocating malformed CSP rows.
    # The exception amount is indicative only and is never merged into matched CSP rows.
    quality=out['source_data_quality'] or {}
    valid_total=out.get('total') or {}
    indicative=float(quality.get('indicative_commission_not_approved') or 0.0)
    excluded_count=int(quality.get('excluded_enrollment_count') or 0)
    out['full_source_control']={
        'valid_csp_expected_commission':round(float(valid_total.get('expected_commission') or 0.0),2),
        'unresolved_source_enrollments':excluded_count,
        'unresolved_source_commission_indicative_not_approved':round(indicative,2),
        'full_source_expected_commission_indicative':round(float(valid_total.get('expected_commission') or 0.0)+indicative,2),
        'full_bc_actual_commission':round(float(valid_total.get('actual_commission') or 0.0),2),
        'warning':'Full-source expected commission includes indicative amounts for invalid/missing CSP codes. Do not treat this as approved CSP-level reconciliation until source IDs are resolved.'
    }
    return out

def _infer_passbook_rate_from_paid(actual_commission, bc_count, approved_rates):
    """Return an approved rate only when BC's unit payout exactly matches the approved allow-list."""
    try:
        count = float(bc_count)
        actual = float(actual_commission)
    except (TypeError, ValueError):
        return None
    allowed = []
    for value in approved_rates.values():
        try:
            allowed.append(float(value))
        except (TypeError, ValueError):
            continue
    if count <= 0 or not allowed:
        return None
    implied = actual / count
    matches = [rate for rate in allowed if abs(implied - rate) < 0.0001]
    return matches[0] if len(matches) == 1 else None


@router.get('/passbook-printing')
def passbook_printing():
    """Independent monthly passbook control; does not require core transaction/rate batch.

    The CSP-wise source only provides print counts, so the five-print/account/month cap
    cannot be verified. Expected amount is therefore indicative until account-level
    evidence and the approved rate master confirm eligibility.
    """
    if not CM.exists():
        return {'available':False,'status':'COMMISSION_SOURCE_REQUIRED','message':'Upload the matching-period BC commission report first.','rows':[],'total':{}}
    if not PB.exists():
        return {'available':False,'status':'PASSBOOK_SOURCE_REQUIRED','message':'Upload the current-period Passbook Printing CSP-wise source.','rows':[],'total':{}}
    source=load_passbook_printing_counts()
    if source.empty:
        return {'available':False,'status':'PASSBOOK_SOURCE_EMPTY','message':'No valid dated Passbook Printing CSP counts are available.','rows':[],'total':{}}
    cm=pd.read_csv(CM,low_memory=False)
    required={'csp_id','transaction_type','report_base','actual_commission'}
    if not required.issubset(cm.columns):
        return {'available':False,'status':'INVALID_COMMISSION_SCHEMA','message':'Normalized BC commission source is missing CSP/type/count/commission fields. Re-upload the BC report.','rows':[],'total':{}}
    src=source.copy()
    src['csp_id']=src['csp_id'].map(norm)
    src['count']=pd.to_numeric(src['count'],errors='coerce')
    src['period']=src['period'].map(_period_month)
    src=src[src['csp_id'].str.match(r'^1A85\d{4}$',na=False) & src['count'].gt(0) & src['period'].notna()].copy()
    cm['csp_id']=cm['csp_id'].map(norm); cm['transaction_type']=cm['transaction_type'].map(norm)
    cm['report_base']=pd.to_numeric(cm['report_base'],errors='coerce'); cm['actual_commission']=pd.to_numeric(cm['actual_commission'],errors='coerce')
    cm=cm[cm['transaction_type'].eq('PASSBOOK PRINTING') & cm['csp_id'].str.match(r'^1A85\d{4}$',na=False)].copy()
    # One uploaded BC report represents one monthly control. Never join an August source
    # against a differently dated commission report when date metadata is available.
    meta=load_metadata(); cm_meta=meta.get('commission') or {}; source_meta=meta.get('passbook_printing_counts') or {}
    source_periods=sorted(src['period'].dropna().unique().tolist())
    cs,ce=cm_meta.get('period_start'),cm_meta.get('period_end')
    if cs and ce and source_periods:
        covered=set(pd.period_range(pd.Timestamp(cs),pd.Timestamp(ce),freq='M').astype(str).tolist())
        if not set(source_periods).issubset(covered):
            return {'available':False,'status':'PERIOD_MISMATCH','message':f'Passbook source period {", ".join(source_periods)} does not match BC report period {cs} to {ce}.','source_periods':source_periods,'rows':[],'total':{}}
    src=src.groupby('csp_id',as_index=False).agg(source_count=('count','sum'),period=('period',lambda x: ','.join(sorted(set(x)))))
    bc=cm.groupby('csp_id',as_index=False).agg(bc_count=('report_base',lambda x:x.sum(min_count=1)),actual_commission=('actual_commission',lambda x:x.sum(min_count=1)),channel=('channel',lambda x: next(iter(set(str(v).strip().upper() for v in x.dropna() if str(v).strip())),'' ) if 'channel' in cm.columns else ''))
    keys=pd.DataFrame({'csp_id':sorted(set(src.csp_id)|set(bc.csp_id))})
    x=keys.merge(src,on='csp_id',how='left').merge(bc,on='csp_id',how='left')
    for col in ['source_count','bc_count','actual_commission']: x[col]=pd.to_numeric(x[col],errors='coerce').fillna(0)
    # Normalize geography deterministically. Conflicting or unknown BC POPULATION
    # values must not be resolved by arbitrary row order.
    def _normalize_passbook_population(value):
        value = norm(value).replace('_', ' ').replace('-', ' ')
        if value in {'RURAL', 'SEMI URBAN', 'SEMIURBAN'}:
            return 'RURAL'
        if value in {'URBAN', 'METRO', 'URBAN METRO'}:
            return 'URBAN'
        return ''
    if 'channel' in cm.columns:
        # Geography belongs to the CSP, not to a particular transaction type.
        # The BC commission report may have no PASSBOOK PRINTING row for a CSP
        # when the count comes from the supplemental print-count source. Restricting
        # geography lookup to passbook rows therefore made the approved ₹5/₹6 rate
        # disappear even when that CSP's area was present on its other BC rows.
        # Aggregate all current-period BC rows by CSP and accept only one unambiguous
        # normalized geography; conflicting geography remains unresolved.
        channel_values = cm.groupby('csp_id')['channel'].agg(
            lambda values: sorted({_normalize_passbook_population(v) for v in values if _normalize_passbook_population(v)})
        ).to_dict()
        x['channel_candidates'] = x['csp_id'].map(lambda c: channel_values.get(c, []))
        x['channel'] = x['channel_candidates'].map(lambda vals: vals[0] if len(vals) == 1 else '')
        x['geography_conflict'] = x['channel_candidates'].map(lambda vals: len(vals) > 1)
    else:
        x['channel_candidates'] = [[] for _ in range(len(x))]
        x['channel'] = ''
        x['geography_conflict'] = False
    # Use the approved permanent SBI rate master rather than a duplicate hardcoded
    # rate table, so a future approved rule revision has one source of truth.
    approved_path = BASE_DIR / 'data' / 'rate_master' / 'approved_rule_master_reference.csv'
    approved_rates = {}
    if approved_path.exists():
        approved = pd.read_csv(approved_path, dtype=str).fillna('')
        approved = approved[approved.get('transaction_type', pd.Series('', index=approved.index)).map(norm).eq('PASSBOOK PRINTING')]
        for _, rule in approved.iterrows():
            status = norm(rule.get('rule_status', ''))
            area = _normalize_passbook_population(rule.get('channel', ''))
            try: rate_value = float(rule.get('rate', ''))
            except (TypeError, ValueError): continue
            if status == 'CONFIRMED' and area:
                if area in approved_rates and approved_rates[area] != rate_value:
                    approved_rates[area] = None
                else:
                    approved_rates[area] = rate_value
    x['rate'] = x['channel'].map(approved_rates)
    x['rate_source'] = x['rate'].map(lambda v: 'APPROVED_GEOGRAPHY_MASTER' if pd.notna(v) else '')
    x.loc[x['geography_conflict'], 'rate'] = pd.NA
    x.loc[x['geography_conflict'], 'rate_source'] = ''

    # Fallback for this rule only: the BC commission sheet encodes the paid rate
    # as commission / reported print count. Accept it only when it exactly equals
    # one of the permanent, confirmed SBI rates (₹5 rural or ₹6 urban). This does
    # not infer a new rate from arbitrary payout values; the permanent master is
    # the allow-list. The source is clearly labelled as BC-implied and remains
    # provisional because it is not an independent CSP geography classification.
    if approved_rates and 'rate' in x.columns:
        for idx, row in x.iterrows():
            if pd.notna(row.get('rate')) or bool(row.get('geography_conflict')):
                continue
            match_rate = _infer_passbook_rate_from_paid(
                row.get('actual_commission'), row.get('bc_count'), approved_rates
            )
            if match_rate is not None:
                x.at[idx, 'rate'] = match_rate
                x.at[idx, 'rate_source'] = 'BC_PAID_UNIT_RATE_MATCHES_APPROVED_SBI_RATE_PROVISIONAL'

    x['expected_commission_indicative'] = x['source_count'] * x['rate']
    x['count_difference_source_minus_bc']=x['source_count']-x['bc_count']
    x['commission_difference_actual_minus_expected']=x['actual_commission']-x['expected_commission_indicative']
    x['cap_status']='NOT_VERIFIABLE_ACCOUNT_LEVEL_SOURCE'
    x['status']=x.apply(lambda r:'GEOGRAPHY_UNRESOLVED' if pd.isna(r['rate']) else ('MATCHED_COUNTS' if abs(r['count_difference_source_minus_bc'])<1e-9 else 'COUNT_MISMATCH'),axis=1)
    rows=rec(x)
    # Malformed source identities are never silently counted as matched or fuzzy-mapped.
    # Surface their print counts as unresolved source exceptions alongside valid CSP rows.
    exception_path=BASE_DIR/'data'/'supplemental'/'latest_passbook_printing_count_exceptions.csv'
    exception_rows=[]; exception_prints=0
    if exception_path.exists():
        try:
            ex=pd.read_csv(exception_path,dtype=str).fillna('')
            if 'period' in ex.columns:
                ex=ex[ex['period'].map(_period_month).isin(source_periods)].copy()
            if not ex.empty:
                ex['count']=pd.to_numeric(ex['count'],errors='coerce').fillna(0)
                exception_prints=int(ex['count'].sum())
                exception_rows=rec(ex)
        except Exception:
            exception_rows=[]; exception_prints=0
    return {'available':True,'status':'READY_WITH_SOURCE_EXCEPTIONS' if exception_rows else 'READY','source_file':source_meta.get('filename'),'commission_file':cm_meta.get('filename'),'source_periods':source_periods,'source_limit':'CSP-wise counts only; account-level 5-print cap cannot be independently verified; expected amount is indicative, not settlement-approved.','source_identity_exceptions':exception_rows,'total':{'source_prints':int(x['source_count'].sum()),'unresolved_source_prints':exception_prints,'source_prints_including_unresolved':int(x['source_count'].sum())+exception_prints,'bc_prints':int(x['bc_count'].sum()),'count_difference_source_minus_bc_excluding_unresolved':int(x['source_count'].sum()-x['bc_count'].sum()),'count_difference_including_unresolved':int(x['source_count'].sum())+exception_prints-int(x['bc_count'].sum()),'expected_commission_indicative':round(float(x['expected_commission_indicative'].sum(min_count=1) or 0),2),'actual_commission':round(float(x['actual_commission'].sum()),2),'commission_difference_actual_minus_expected':round(float(x['actual_commission'].sum()-x['expected_commission_indicative'].sum(min_count=1)),2),'geography_unresolved_csp_count':int(x['rate'].isna().sum()),'geography_conflict_csp_count':int(x['geography_conflict'].sum()),'source_identity_exception_count':len(exception_rows),'account_level_cap_verified':False},'rows':rows}

@router.get('/transaction-type')
def txn_type(): return rec(aggregate_by_transaction_type(load_result()))
@router.get('/csp-type')
def csp_type(): return rec(aggregate_by_csp_and_type(load_result()))
@router.get('/exceptions')
def exceptions(): return rec(build_exceptions(load_result()))

@router.get('/condition-audit')
def condition_audit(offset:int=0, limit:int=100, status:str|None=None, search:str|None=None):
    _require_sources()
    if not AUDIT.exists():
        load_result(force=False)
    if not AUDIT.exists():
        raise HTTPException(404,'SBI condition audit is not available. Run reconciliation first.')
    df=pd.read_csv(AUDIT,low_memory=False)
    if status:
        df=df[df['condition_status'].astype('string').str.upper().eq(status.upper())]
    if search:
        q=search.strip().upper()
        mask=df.astype(str).apply(lambda c:c.str.upper().str.contains(q,regex=False,na=False)).any(axis=1)
        df=df[mask]
    total=len(df)
    rows=df.iloc[max(0,offset):max(0,offset)+max(1,min(limit,500))]
    return {'total':total,'offset':max(0,offset),'limit':max(1,min(limit,500)),'rows':rec(rows)}

@router.get('/condition-audit/summary')
def condition_audit_summary():
    _require_sources()
    if not AUDIT_SUMMARY.exists():
        load_result(force=False)
    if not AUDIT_SUMMARY.exists():
        raise HTTPException(404,'SBI condition audit is not available. Run reconciliation first.')
    import json
    return json.loads(AUDIT_SUMMARY.read_text())

@router.get('/time')
def time_view(grain:str='day', start_date:str|None=None, end_date:str|None=None, csp_id:str|None=None, transaction_type:str|None=None):
    if grain not in {'day','month'}: raise HTTPException(400,'grain must be day or month')
    _require_sources()
    if not RM.exists(): raise HTTPException(400,'Upload and validate the approved rate/slab master first.')
    tx=pd.read_csv(TX,low_memory=False); cm=pd.read_csv(CM,low_memory=False); rules=pd.read_csv(RM,low_memory=False)
    sig=_signature(); import hashlib, json; key=hashlib.sha256(json.dumps({**sig,'grain':grain,'start_date':start_date,'end_date':end_date,'csp_id':csp_id,'transaction_type':transaction_type},sort_keys=True).encode()).hexdigest()[:20]
    meta=load_metadata(); gran=(meta.get('commission') or {}).get('date_granularity') or 'date'
    return rec(time_reconciliation(tx,cm,rules,grain=grain,cache_key=key,commission_date_granularity=gran,start_date=start_date,end_date=end_date,csp_id=csp_id,transaction_type=transaction_type))

@router.get('/transactions')
def transactions(limit:int=500):
    meta=load_metadata();
    if not TX.exists() or not CM.exists(): raise HTTPException(400,'Upload both transaction and commission files first.')
    if not meta.get('transactions') or not meta.get('commission') or meta['transactions'].get('batch_id') != meta['commission'].get('batch_id'):
        raise HTTPException(400,'Transaction and commission files are from different upload batches.')
    tx=load_successful_transactions(TX); tx['csp_id']=tx['csp_id'].map(norm); tx['transaction_type']=tx['transaction_type'].map(norm); mapped=tx.apply(lambda x: map_transaction(x.get('transaction_type'), x.get('amount')), axis=1); tx['join_type']=[x[0] for x in mapped]; tx['rule_type']=[x[1] for x in mapped]
    if RM.exists():
        rules=pd.read_csv(RM,low_memory=False); mapped=tx[tx['join_type'].notna()].copy(); mapped['rule_type']=mapped['join_type']; mapped.loc[mapped['transaction_type'].eq('INITIAL DEPOSIT'),'rule_type']='ACCOUNT OPPENING (PMJDY)'; mapped,_=add_expected_commission(mapped,rules);
        for c in ['expected_commission','commission_rule_id','rate_status','condition_failure','required_evidence_missing']:
            if c not in mapped.columns: mapped[c]=pd.NA
        tx.loc[mapped.index,['expected_commission','commission_rule_id','rate_status','condition_failure','required_evidence_missing']]=mapped[['expected_commission','commission_rule_id','rate_status','condition_failure','required_evidence_missing']]
    else:
        tx['expected_commission']=pd.NA; tx['commission_rule_id']=pd.NA; tx['rate_status']='Rate Master Missing'
    if 'rate_status' not in tx.columns:
        tx['rate_status']='Rate Master Missing'
    if 'expected_commission' not in tx.columns:
        tx['expected_commission']=pd.NA
    tx['verified_expected_commission']=pd.to_numeric(tx.get('expected_commission'),errors='coerce').where(
        tx.get('rate_status','').astype('string').str.startswith('Applied') &
        ~tx.get('rate_status','').astype('string').str.contains('Pending Mapping',na=False)
    )
    tx['condition_status']=tx['verified_expected_commission'].notna().map({True:'OK',False:'CONDITIONAL'}).astype('string')
    tx.loc[tx.get('rate_status','').astype('string').eq('Condition Failed'),'condition_status']='CONDITION FAIL'
    tx.loc[tx['join_type'].isna(),'condition_status']='UNMAPPED'
    tx['actual_commission_matching_basis']='CSP + Transaction Type aggregate (BC report has no transaction reference)'
    cols=[c for c in ['transaction_id','csp_id','transaction_type','join_type','transaction_date','amount','expected_commission','verified_expected_commission','commission_rule_id','rate_status','condition_status','actual_commission_matching_basis'] if c in tx.columns]
    return rec(tx[cols].head(max(1,min(limit,5000))) )
@router.get('/export')
def export(format:str=Query('xlsx',pattern='^(xlsx|csv)$')):
    r=load_result()
    if format=='csv':
        return StreamingResponse(BytesIO(r.to_csv(index=False).encode('utf-8-sig')),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=revenue_reconciliation_report.csv'})

    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from app.services.audit_service import list_runs, sha256_file

    meta=load_metadata()
    status_counts=r['reconciliation_status'].value_counts().to_dict() if 'reconciliation_status' in r else {}
    gap_counts=r['financial_gap_status'].value_counts().to_dict() if 'financial_gap_status' in r else {}
    expected_all=pd.to_numeric(r.get('expected_commission'),errors='coerce')
    if 'settlement_rule_approved' in r:
        expected_mask=r['settlement_rule_approved'].fillna(False) & expected_all.notna()
    else:
        expected_mask=expected_all.notna()
    expected=expected_all[expected_mask]
    actual=pd.to_numeric(r.get('actual_comparable_commission'),errors='coerce')
    variance=pd.to_numeric(r.get('variance'),errors='coerce')
    controls=pd.DataFrame([
        ['Report generated (UTC)', pd.Timestamp.utcnow().isoformat()],
        ['Transaction file', meta.get('transactions',{}).get('filename')],
        ['Commission file', meta.get('commission',{}).get('filename')],
        ['Rate/Slab master', meta.get('rate_master',{}).get('filename')],
        ['Period start', meta.get('transactions',{}).get('period_start')],
        ['Period end', meta.get('transactions',{}).get('period_end')],
        ['Successful transactions', int(r.successful_transactions.sum())],
        ['Reconciliation groups', int(len(r))],
        ['Matched groups', int(status_counts.get('MATCH',0))],
        ['Count mismatch groups', int(status_counts.get('SOURCE_COUNT_DIFFERENCE',0))],
        ['Shortfall groups', int(gap_counts.get('Shortfall',0))],
        ['Excess groups', int(gap_counts.get('Excess',0))],
        ['Missing commission groups', int(((r.successful_transactions > 0) & r.join_type.notna() & pd.to_numeric(r.actual_commission, errors='coerce').isna()).sum()) if 'join_type' in r.columns and 'actual_commission' in r.columns else 0],
        ['BC-only groups', int(status_counts.get('BC_ONLY_ACTIVITY',0))],
        ['Rate master missing groups', int(status_counts.get('RATE_MASTER_MISSING',0))],
        ['Ambiguous rate groups', int(status_counts.get('AMBIGUOUS_RATE_RULE',0))],
        ['Unmapped transaction groups', int(status_counts.get('UNMAPPED',0))],
        ['Expected commission', round(float(expected.sum()),2) if expected.notna().any() else None],
        ['Calculated expected commission (all rule-covered rows)', round(float(expected_all.sum()),2) if expected_all.notna().any() else None],
        ['Actual commission', round(float(actual.sum()),2) if actual.notna().any() else None],
        ['Comparable Actual Commission', round(float(actual.sum()),2) if actual.notna().any() else None],
        ['Financial Gap (Expected - Comparable Actual)', round(float(variance.sum()),2) if variance.notna().any() else None],
        ['Shortfall Amount', round(float(variance.clip(lower=0).sum()),2) if variance.notna().any() else None],
        ['Excess Amount', round(float((-variance.clip(upper=0)).sum()),2) if variance.notna().any() else None],
        ['Calculation policy', 'Deterministic approved rate/slab rules only; actual commission is never used to infer rates.'],
    ], columns=['Control','Value'])

    out=BytesIO()
    with pd.ExcelWriter(out,engine='openpyxl') as w:
        controls.to_excel(w,index=False,sheet_name='Control_Summary')
        r.to_excel(w,index=False,sheet_name='CSP_Type_Reconciliation')
        aggregate_by_csp(r).to_excel(w,index=False,sheet_name='CSP_Wise')
        aggregate_by_transaction_type(r).to_excel(w,index=False,sheet_name='Transaction_Type')
        aggregate_by_csp_and_type(r).to_excel(w,index=False,sheet_name='CSP_Type')
        build_exceptions(r).to_excel(w,index=False,sheet_name='Exceptions')
        if RM.exists(): pd.read_csv(RM).to_excel(w,index=False,sheet_name='Rate_Master_Used')
        # Period analysis is date-driven. If the BC source has no date field, actual
        # commission is intentionally shown as unavailable by day; no artificial daily allocation is made.
        # Rural Commission is a separate incentive control driven by the current-period Rural CSP login list and the user-approved TXN Types mapping.
        try:
            rc = reconcile_rural_commission(pd.read_csv(CM,low_memory=False), transaction_month=_single_calendar_month_from_transactions(pd.read_csv(TX,low_memory=False)))
            if rc.get('available'):
                pd.DataFrame(rc.get('rows',[])).to_excel(w,index=False,sheet_name='Rural_Commission_Reconciliation')
                pd.DataFrame([rc.get('summary',{})]).to_excel(w,index=False,sheet_name='Rural_Commission_Summary')
                load_txn_mapping().to_excel(w,index=False,sheet_name='Rural_TXN_Types')
        except Exception as e:
            pd.DataFrame([{'error':str(e)}]).to_excel(w,index=False,sheet_name='Rural_Commission_Control')

        if RM.exists():
            try: time_reconciliation(pd.read_csv(TX,low_memory=False),pd.read_csv(CM,low_memory=False),pd.read_csv(RM,low_memory=False),'day',commission_date_granularity=(meta.get('commission') or {}).get('date_granularity') or 'date').to_excel(w,index=False,sheet_name='Daily_Reconciliation')
            except Exception as e: pd.DataFrame([{'error':str(e)}]).to_excel(w,index=False,sheet_name='Daily_Reconciliation')
            try: time_reconciliation(pd.read_csv(TX,low_memory=False),pd.read_csv(CM,low_memory=False),pd.read_csv(RM,low_memory=False),'month',commission_date_granularity=(meta.get('commission') or {}).get('date_granularity') or 'date').to_excel(w,index=False,sheet_name='Monthly_Reconciliation')
            except Exception as e: pd.DataFrame([{'error':str(e)}]).to_excel(w,index=False,sheet_name='Monthly_Reconciliation')
        source_controls=[]
        for kind,label,path in [('transactions','Transaction',TX),('commission','Commission',CM),('rate_master','Rate Master',RM),('rural_csp','Rural CSP Eligibility',RURAL)]:
            m=meta.get(kind) or {}
            val=m.get('validation') or {}
            source_controls.append([label,m.get('filename'),m.get('sheet_name'),m.get('rows'),m.get('raw_rows'),m.get('blank_rows_after_header'),val.get('processable_rows'),val.get('excluded_rows'),val.get('missing_transaction_date'),m.get('period_start'),m.get('period_end'),sha256_file(path) if path.exists() else None])
        pd.DataFrame(source_controls,columns=['Source','Filename','Worksheet','Stored Rows','Physical Rows After Header','Blank Rows Ignored','Processable Rows','Excluded Rows','Missing Transaction Date Rows','Period Start','Period End','SHA-256']).to_excel(w,index=False,sheet_name='Source_Control')
        runs=list_runs(50)
        if runs: pd.DataFrame(runs).to_excel(w,index=False,sheet_name='Audit_Run_Log')
        # Source hashes make the exported report reproducible/auditable.
        hashes=pd.DataFrame([
            ['Transaction SHA-256', sha256_file(TX)],
            ['Commission SHA-256', sha256_file(CM)],
            ['Rate Master SHA-256', sha256_file(RM)],
            ['Rural CSP Source SHA-256', sha256_file(RURAL) if RURAL.exists() else None],
            ['Rural TXN Mapping SHA-256', sha256_file(Path(__file__).resolve().parents[1] / 'data' / 'rural_csp' / 'rural_transaction_type_mapping.csv')],
        ], columns=['Source','SHA-256'])
        hashes.to_excel(w,index=False,sheet_name='Source_Integrity')
        for ws in w.book.worksheets:
            ws.freeze_panes='A2'
            ws.auto_filter.ref=ws.dimensions
            for cell in ws[1]:
                cell.font=Font(bold=True,color='FFFFFF')
                cell.fill=PatternFill('solid',fgColor='0F766E')
                cell.alignment=Alignment(horizontal='center',vertical='center')
            for col in ws.columns:
                max_len=0
                for c in list(col)[:300]:
                    max_len=max(max_len,len(str(c.value)) if c.value is not None else 0)
                ws.column_dimensions[get_column_letter(col[0].column)].width=min(max(max_len+2,10),45)
    out.seek(0)
    return StreamingResponse(out,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename=revenue_reconciliation_audit_report.xlsx'})
