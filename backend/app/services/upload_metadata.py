import json, uuid
from pathlib import Path
from datetime import datetime, timezone
BASE_DIR=Path(__file__).resolve().parents[1]; META=BASE_DIR/'data'/'upload_metadata.json'

def _default(): return {'transactions':None,'commission':None,'rate_master':None,'csp_geography':None,'rural_csp':None,'social_security_counts':None,'passbook_printing_counts':None,'dfs_incentive':None,'women_csp_roster':None,'tab_incentive':None,'loan_lead_generation':None,'expected_commission_rule':None,'active_batch_id':None,'upload_attempt_errors':{}}
def load_metadata():
    if not META.exists(): return _default()
    try:
        data=json.loads(META.read_text(encoding='utf-8'))
        for k in ('transactions','commission','rate_master','csp_geography','rural_csp','social_security_counts','passbook_printing_counts','dfs_incentive','women_csp_roster','tab_incentive','loan_lead_generation','expected_commission_rule'): data.setdefault(k,None)
        data.setdefault('active_batch_id',None); data.setdefault('upload_attempt_errors',{}); return data
    except Exception: return _default()

def _write(data):
    META.parent.mkdir(parents=True,exist_ok=True); META.write_text(json.dumps(data,indent=2),encoding='utf-8'); return data

def prepare_source_upload(kind, sha256=None):
    """Prepare a source upload while keeping a multi-file period batch coherent.

    Replacing either the transaction file or BC commission file starts a new batch
    only once. Uploading its matching companion file then joins that same batch,
    rather than accidentally creating a second batch and making reconciliation
    impossible. The approved rate master is a reusable ruleset; retain it across
    monthly data batches and bind it to the active batch for validation. Period-bound
    supplements are retained as evidence but the reconciliation engine filters them
    by the transaction month.
    """
    data=load_metadata()
    existing=data.get(kind) or {}
    other_kind='commission' if kind=='transactions' else 'transactions'
    other=data.get(other_kind) or {}
    same_file=bool(sha256 and existing.get('sha256')==sha256)

    if kind in ('transactions','commission') and existing and not same_file:
        active=data.get('active_batch_id')
        # If the companion source has already been uploaded into the active batch,
        # this is a replacement of an already coherent batch and needs a new ID.
        # Otherwise it is the second half of the same new batch and must join it.
        if not active:
            data['active_batch_id']=uuid.uuid4().hex
        elif existing.get('batch_id') == active and other.get('batch_id') == active:
            # Both files currently belong to the active, already coherent batch:
            # replacing the first one starts a new batch.
            data['active_batch_id']=uuid.uuid4().hex
        elif other.get('batch_id') != active:
            # No companion file has joined the active batch yet; start a new one.
            data['active_batch_id']=uuid.uuid4().hex
        # Otherwise this is the second source being replaced: join the active batch.
        active=data.get('active_batch_id')
        if data.get('rate_master'):
            data['rate_master']['batch_id']=active
    elif not data.get('active_batch_id'):
        data['active_batch_id']=(other or existing).get('batch_id') or uuid.uuid4().hex

    return _write(data)

def save_source(kind, filename, sheet_name, rows, period_start=None, period_end=None, extra=None, sha256=None):
    data=load_metadata(); batch=data.get('active_batch_id') or uuid.uuid4().hex
    item={'filename':filename,'sheet_name':sheet_name,'rows':int(rows),'uploaded_at':datetime.now(timezone.utc).isoformat(),
          'period_start':period_start,'period_end':period_end,'batch_id':batch,'sha256':sha256}
    if extra: item.update(extra)
    data[kind]=item; data['active_batch_id']=batch
    # A successful replacement resolves any prior failed-attempt blocker for this source.
    attempts=data.setdefault('upload_attempt_errors',{})
    attempts.pop(kind, None)
    return _write(data)

def clear_source(kind):
    data=load_metadata(); data[kind]=None; return _write(data)


def period_from_series(series):
    import pandas as pd
    if series is None:
        return None,None
    from .number_parser import parse_date_series
    d=parse_date_series(series)
    if not d.notna().any(): return None,None
    return d.min().date().isoformat(), d.max().date().isoformat()


def record_upload_failure(kind, filename, message):
    """Record a failed core upload attempt without replacing the last normalized file.

    The previous bytes remain available for diagnosis, but reconciliation status must
    block until a successful upload resolves this attempt so stale data cannot be used silently.
    """
    data=load_metadata()
    attempts=data.setdefault('upload_attempt_errors',{})
    attempts[kind]={
        'filename':str(filename or ''),
        'message':str(message or 'Upload failed validation.'),
        'attempted_at':datetime.now(timezone.utc).isoformat(),
    }
    return _write(data)


def clear_upload_failure(kind):
    data=load_metadata()
    attempts=data.setdefault('upload_attempt_errors',{})
    attempts.pop(kind, None)
    return _write(data)
