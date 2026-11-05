from pathlib import Path
from typing import Optional
import hashlib
import json
import re
import calendar
from io import BytesIO
import pandas as pd
from app.services import excel_io
from fastapi import APIRouter,UploadFile,File,Form,HTTPException
from app.services.file_processor import read_uploaded_file,normalize_columns,clean_string_columns,preview_dataframe
from app.services.validator import validate_transaction_data,validate_commission_data
from app.services.rate_master import validate_rate_master, build_rate_master_from_workbook
from app.services.number_parser import parse_date_series
from app.services.upload_metadata import save_source,load_metadata,prepare_source_upload,period_from_series,clear_source,record_upload_failure,clear_upload_failure
from app.services.processing_snapshot import build_snapshot,save_snapshot
from app.services.reconciliation_cache import clear_cache
from app.services.rural_commission import parse_rural_csp_workbook, parse_rural_csp_csv, save_rural_master, RURAL_MASTER_PATH

from app.services.result_memo import memo_on_files
router=APIRouter(); BASE_DIR=Path(__file__).resolve().parents[1]
TX=BASE_DIR/'data'/'transactions'; CM=BASE_DIR/'data'/'commissions'; RM=BASE_DIR/'data'/'rate_master'; GEO=BASE_DIR/'data'/'csp_geography'
RURAL=BASE_DIR/'data'/'rural_csp'
SUPPLEMENTAL=BASE_DIR/'data'/'supplemental'
SOCIAL_COUNTS=SUPPLEMENTAL/'latest_social_security_counts.csv'
SOCIAL_EXCEPTIONS_PATH=SUPPLEMENTAL/'latest_social_security_counts_exceptions.csv'
PASSBOOK_COUNTS=SUPPLEMENTAL/'latest_passbook_printing_counts.csv'
PASSBOOK_EXCEPTIONS=SUPPLEMENTAL/'latest_passbook_printing_count_exceptions.csv'
DFS_COUNTS=SUPPLEMENTAL/'latest_dfs_incentive_counts.csv'
DFS_META=SUPPLEMENTAL/'latest_dfs_incentive_metadata.json'
WOMEN_COUNTS=SUPPLEMENTAL/'latest_women_csp_roster.csv'
WOMEN_META=SUPPLEMENTAL/'latest_women_csp_roster_metadata.json'
CSP_IDENTITY=SUPPLEMENTAL/'latest_csp_identity_crosswalk.csv'
CSP_IDENTITY_META=SUPPLEMENTAL/'latest_csp_identity_crosswalk_metadata.json'
EXPECTED_RULE_DIR=BASE_DIR/'data'/'expected_commission_rule'
EXPECTED_RULE_PATH=EXPECTED_RULE_DIR/'latest.xlsx'
EXPECTED_RULE_DIR.mkdir(parents=True,exist_ok=True)
# Permanent DFS Monthly Target & Extra Incentive Matrix from the user's approved rule image.
# The monthly amount is determined by the slab assigned in the uploaded current-period CSP sheet.
DFS_RATES={'SLAB-1':1200.0,'SLAB-2':1500.0,'SLAB-3':1800.0,'SLAB-4':2200.0,'SUPER SLAB':5000.0}
DFS_RULE_MATRIX={
    'schemes': [
        {'scheme':'PMJDY (Account Opening)','targets':{'SLAB-1':8,'SLAB-2':10,'SLAB-3':12,'SLAB-4':14,'SUPER SLAB':30}},
        {'scheme':'PMJJBY (Life Insurance)','targets':{'SLAB-1':12,'SLAB-2':14,'SLAB-3':16,'SLAB-4':18,'SUPER SLAB':50}},
        {'scheme':'PMSBY (Accident Insurance)','targets':{'SLAB-1':20,'SLAB-2':25,'SLAB-3':30,'SLAB-4':35,'SUPER SLAB':100}},
        {'scheme':'APY (Atal Pension Yojana)','targets':{'SLAB-1':3,'SLAB-2':4,'SLAB-3':5,'SLAB-4':6,'SUPER SLAB':15}},
    ],
    'monthly_extra_incentive_inr': dict(DFS_RATES),
    'average_balance_multiplier_percent': {'SLAB-1':0.85,'SLAB-2':0.90,'SLAB-3':0.95,'SLAB-4':1.00,'SUPER SLAB':1.00},
    'source':'User-provided DFS Monthly Target & Extra Incentive Matrix image',
    'eligibility_note':'Targets are stored as permanent rule metadata. Slab is not inferred from this matrix unless current-period CSP-wise counts for all four schemes are supplied and the slab assignment rule is explicitly confirmed.',
    'average_balance_note':'Average Balance Multiplier / Comm. percentages are stored separately from the monthly extra incentive. A financial amount cannot be calculated without the applicable average-balance base and its approved calculation definition.'
}
for p in (TX,CM,RM,GEO,RURAL,SUPPLEMENTAL): p.mkdir(parents=True,exist_ok=True)
MAX=100*1024*1024
RATE_MASTER_PARSER_VERSION='62.6.108-windows-path-install-fix'
COMMISSION_PARSER_VERSION='60.0.0-final-audit-commission-geography'
TRANSACTION_PARSER_VERSION='60.0.0-final-audit-transaction-validation'


def _json_safe(value):
    """Recursively convert pandas/numpy NaN, timestamps and scalar types to strict JSON-safe values."""
    import math
    from datetime import date, datetime
    import numpy as np
    import pandas as pd
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (float, np.floating)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value.item() if hasattr(value, 'item') else value


def _response(payload):
    return _json_safe(payload)

def _strip_accidental_header_row(df):
    """Return source data without a duplicated header-as-data row.

    Some spreadsheet exports/cached snapshots can contain the column header as
    the first record. That row is not a transaction/commission record and must
    never be counted or displayed as source data.
    """
    if df is None or df.empty:
        return df
    first = df.iloc[0]
    columns = list(df.columns)
    if len(first) != len(columns):
        return df
    same = all(('' if pd.isna(v) else str(v).strip().lower()) == str(c).strip().lower()
               for v, c in zip(first.tolist(), columns))
    return df.iloc[1:].reset_index(drop=True) if same else df

def _refresh_processing_snapshot():
    # Rebuild the transaction-processing snapshot whenever any commercial reference
    # source changes. The snapshot's amount-sensitive mappings (Initial deposit,
    # Customer enroll for SSS) must not remain stale when the user uploads the
    # transaction file before the commission/rate master files.
    if not TX.joinpath('latest_transactions.csv').exists():
        return
    try:
        tx_df=pd.read_csv(TX/'latest_transactions.csv',low_memory=False)
        save_snapshot(build_snapshot(tx_df, load_metadata().get('transactions')))
    except Exception:
        # Snapshot refresh is a UI optimization; reconciliation itself reads the
        # authoritative normalized sources and must not fail because of this cache.
        pass

async def _read(file,sheet_name,kind):
    if not file.filename.lower().endswith(('.csv','.xlsx')): raise HTTPException(400,'Only CSV and XLSX files are supported.')
    content=await file.read()
    if not content: raise HTTPException(400,'The uploaded file is empty.')
    if len(content)>MAX: raise HTTPException(413,'File is larger than the 100 MB upload limit.')
    sha=hashlib.sha256(content).hexdigest()
    return content,sha

def _cached_response(kind, filename, sha):
    """Return a fast response when the exact same file is uploaded again."""
    meta=load_metadata().get(kind) or {}
    if meta.get('sha256') != sha: return None
    target={'transactions':TX/'latest_transactions.csv','commission':CM/'latest_commission.csv','rate_master':RM/'latest_rate_master.csv','csp_geography':GEO/'latest_csp_geography.csv','rural_csp':RURAL_MASTER_PATH}[kind]
    if not target.exists(): return None
    try:
        validation=meta.get('validation')
        if not validation: return None
        # Do not reuse a failed/old rate-master validation after the parser has
        # learned the workbook's multi-sheet SBI structure.
        if kind=='rate_master' and validation.get('parser_version') != RATE_MASTER_PARSER_VERSION:
            return None
        if kind=='commission' and validation.get('parser_version') != COMMISSION_PARSER_VERSION:
            return None
        preview=preview_dataframe(pd.read_csv(target,nrows=10))
        return {'file_type':kind,'filename':filename,'sheet_name':meta.get('sheet_name'),'available_sheets':[],
                'saved':bool(validation.get('valid')),'validation':validation,'columns':validation.get('columns',[]),
                'preview':preview,'cached':True}
    except Exception:
        return None

def _validation_with_columns(v,df):
    v['columns']=list(df.columns)
    return v

def _bc_workbook_source_controls(content, selected_df):
    """Validate the internal accounting controls of the standard SBI BC workbook.

    The CSP-wise sheet is the transaction/type-level reported-commission source.
    Payment Status is the CSP-level payable control (net of evidenced penalties),
    Circle Wise Break Up is the circle-level net control, and Inactive CSP Penalty
    is the explicit penalty evidence. These sheets are controls only; they never
    become an expected-rate source.
    """
    controls = {
        'workbook_internal_control_available': False,
        'csp_wise_gross_commission': None,
        'payment_status_total_commission': None,
        'circle_wise_total_commission': None,
        'inactive_penalty_amount': None,
        'inactive_penalty_realised': None,
        'gross_minus_penalty': None,
        'payment_vs_circle_difference': None,
        'gross_control_difference': None,
        'internal_control_status': 'NOT_APPLICABLE',
        'payment_status_components': {},
        'control_notes': []
    }
    if not str(getattr(content, '__class__', '')).endswith("bytes'>"):
        # bytes-like is expected; simply return not applicable for non-XLSX callers.
        return controls
    try:
        from io import BytesIO
        xl = excel_io.excel_file(content)
        names = {str(x).strip().upper(): x for x in xl.sheet_names}
        required = {'CSP WISE TRANSACTION TYPE WISE', 'PAYMENT STATUS', 'CIRCLE WISE BREAK UP', 'INACTIVE CSP PENALTY'}
        if not required.issubset(set(names)):
            controls['control_notes'].append('Standard SBI BC workbook control sheets were not all present; source-level reconciliation remains available.')
            return controls

        def read(name):
            return excel_io.read_excel(content, sheet_name=names[name], engine='openpyxl')
        csp = read('CSP WISE TRANSACTION TYPE WISE')
        pay = read('PAYMENT STATUS')
        circle = read('CIRCLE WISE BREAK UP')
        penalty = read('INACTIVE CSP PENALTY')

        def num(df, col):
            return pd.to_numeric(df[col], errors='coerce') if col in df.columns else pd.Series(dtype='float64')
        def total(df, col):
            x=num(df,col); v=x.sum(min_count=1)
            return 0.0 if pd.isna(v) else float(v)
        csp_total = total(csp, 'Commission')
        pay_total = total(pay, 'TOTAL COMM')
        circle_total = total(circle, 'TOTAL COMM')
        pen_amount = total(penalty, 'PENALTY AMOUNT')
        pen_realised = total(penalty, 'REALISED PENALTY')
        tol = 0.01
        controls.update({
            'workbook_internal_control_available': True,
            'csp_wise_gross_commission': round(csp_total, 4),
            'payment_status_total_commission': round(pay_total, 4),
            'circle_wise_total_commission': round(circle_total, 4),
            'inactive_penalty_amount': round(pen_amount, 4),
            'inactive_penalty_realised': round(pen_realised, 4),
            'gross_minus_penalty': round(csp_total - pen_realised, 4),
            'payment_vs_circle_difference': round(pay_total - circle_total, 4),
            'gross_control_difference': round(csp_total - (pay_total + pen_realised), 4),
            'payment_status_components': {
                'TXN_COMM': round(total(pay,'TXN COMM'),4),
                'OTHER_TXN_COMM': round(total(pay,'OTHER TXN COMM'),4),
                'AS_COMM': round(total(pay,'AS COMM'),4),
                'INC_COMM': round(total(pay,'INC COMM'),4),
                'RURAL_COMM': round(total(pay,'RURAL COMM'),4),
                'ALR_COMM': round(total(pay,'ALR COMM'),4),
                'REIMBURSEMENTS': round(total(pay,'REIMBURSEMENTS'),4),
            }
        })
        checks = [abs(pay_total-circle_total)<=tol, abs(csp_total-(pay_total+pen_realised))<=tol, abs(pen_amount-pen_realised)<=tol]
        controls['internal_control_status'] = 'PASS' if all(checks) else 'REVIEW'
        if controls['internal_control_status'] == 'PASS':
            controls['control_notes'].append('CSP-wise gross commission = Payment Status total + realised penalty; Payment Status total = Circle Wise net total; penalty amount = realised penalty.')
        else:
            controls['control_notes'].append('One or more internal workbook accounting controls did not reconcile within ₹0.01; review the source workbook before settlement.')
    except Exception as exc:
        controls['control_notes'].append(f'Workbook internal controls could not be calculated: {exc}')
    return controls

@router.post('/transactions')
async def transactions(file:UploadFile=File(...),sheet_name:Optional[str]=Form(None)):
    try:
        content,sha=await _read(file,sheet_name,'transactions')
        # An identical byte-for-byte upload is immutable. Reuse its validated
        # normalized source and processing snapshot instead of reparsing 300k+
        # rows. A parser-version check invalidates the cache automatically after
        # a future validation/parser change.
        cached=_cached_response('transactions',file.filename,sha)
        if cached:
            validation=cached.get('validation') or {}
            if validation.get('parser_version')==TRANSACTION_PARSER_VERSION:
                clear_upload_failure('transactions')
                return _response(cached)
        (df,chosen,sheets,header)=read_uploaded_file(file.filename,content,sheet_name,'transactions')
        raw_display_df = _strip_accidental_header_row(df.copy())
        df=normalize_columns(df)
        std,v=validate_transaction_data(df); v=_validation_with_columns(v,std)
        v['parser_version']=TRANSACTION_PARSER_VERSION
        if not v.get('valid'):
            record_upload_failure('transactions', file.filename, 'Transaction upload did not pass validation: ' + ' | '.join(map(str, v.get('errors') or v.get('missing_columns') or ['source validation failed'])))
        if v['valid']:
            # Keep the uploaded Rural CSP master on disk when transaction data is
            # replaced. The Rural endpoint validates its period against the active
            # transaction month and returns PERIOD_MISMATCH when stale; deleting the
            # source here made upload order fragile and caused valid rural uploads to
            # disappear when the transaction file was uploaded afterwards.
            prepare_source_upload('transactions',sha)
            clear_cache()
            std.to_csv(TX/'latest_transactions.csv',index=False)
            raw_display_df.to_csv(TX/'latest_transactions_raw.csv',index=False)
            period_start,period_end=period_from_series(std['transaction_date']) if 'transaction_date' in std.columns else (None,None)
            extra={'validation':v,'raw_rows':int(df.attrs.get('source_physical_rows_after_header',len(df))),'source_data_rows':int(len(raw_display_df)),'blank_rows_after_header':int(df.attrs.get('blank_rows_after_header',0)),'stored_rows':len(std),'columns_stored':len(std.columns)}
            save_source('transactions',file.filename,chosen,len(std),period_start,period_end,extra=extra,sha256=sha)
            # Build once while the uploaded DataFrame is already in memory. The Processing page then reads this tiny snapshot.
            save_snapshot(build_snapshot(std, load_metadata().get('transactions')))
        v['selected_sheet']=chosen; v['header_row_zero_based']=header
        return _response({'file_type':'transactions','filename':file.filename,'sheet_name':chosen,'available_sheets':sheets,'saved':v['valid'],'validation':v,'columns':list(std.columns),'preview':preview_dataframe(std)})
    except HTTPException as exc:
        record_upload_failure('transactions', getattr(file, 'filename', ''), str(exc.detail))
        raise
    except Exception as e:
        record_upload_failure('transactions', getattr(file, 'filename', ''), str(e))
        raise HTTPException(400,str(e))

def _commission_source_period_bounds(series, granularity=None):
    """Return source period bounds without treating a month label as a single day.

    Commission exports often carry a month/period label (for example, ``Sep 2026``)
    repeated on each row. ``parse_date_series`` normalizes that label to the first
    calendar day, which previously made a full-month report look like a one-day
    source and blocked reconciliation against transactions later in the month.
    """
    if series is None:
        return None, None
    parsed = parse_date_series(series).dropna()
    if parsed.empty:
        return None, None
    if str(granularity or '').strip().lower() == 'month':
        months = parsed.dt.to_period('M')
        first = months.min().start_time.date().isoformat()
        last = months.max().end_time.normalize().date().isoformat()
        return first, last
    return parsed.min().date().isoformat(), parsed.max().date().isoformat()


@router.post('/commission')
async def commission(file:UploadFile=File(...),sheet_name:Optional[str]=Form(None)):
    try:
        content,sha=await _read(file,sheet_name,'commission')
        # Source-data accuracy takes precedence over upload caching. Always re-parse
        # commission uploads so the row-level source snapshot is rebuilt from the
        # current workbook/CSV rather than an older cached snapshot.
        (df,chosen,sheets,header)=read_uploaded_file(file.filename,content,sheet_name,'commission')
        raw_display_df = _strip_accidental_header_row(df.copy())
        df=normalize_columns(df)
        # SBI's CSP-wise commission sheet does not carry Rural/Urban. The same
        # workbook's Payment Status sheet does. Preserve that approved CSP-level
        # population on the normalized commission source so slab rules can select
        # the correct geography without guessing.
        derived_geo = None
        identity_crosswalk = None
        if file.filename.lower().endswith('.xlsx'):
            try:
                from io import BytesIO
                xl=excel_io.excel_file(content)
                ps_name=next((x for x in xl.sheet_names if str(x).strip().upper()=='PAYMENT STATUS'),None)
                # If the workbook uses a different identity-sheet title, discover a
                # sheet with recognizable CSP ID + CSP name columns from this same
                # uploaded BC workbook. Prefer Payment Status whenever present.
                if ps_name is None:
                    for candidate_sheet in xl.sheet_names:
                        try:
                            candidate_df=excel_io.read_excel(content,sheet_name=candidate_sheet,engine='openpyxl')
                            candidate_df=normalize_columns(candidate_df)
                            has_id=any(c in candidate_df.columns for c in ('csp_id','csp_code','csp_code_new','terminal_id'))
                            has_name=any(c in candidate_df.columns for c in ('csp_name','terminal_name','name'))
                            if has_id and has_name:
                                ps_name=candidate_sheet
                                break
                        except Exception:
                            continue
                # Always scan the current BC workbook for a canonical CSP ID/name
                # crosswalk. Previously the fallback scan was nested under `if
                # ps_name`, so it never ran when sheet discovery did not find a
                # recognized identity sheet.
                for candidate_sheet in xl.sheet_names:
                    try:
                        candidate_df=excel_io.read_excel(content,sheet_name=candidate_sheet,engine='openpyxl')
                        candidate_df=normalize_columns(candidate_df)
                        candidate_id_col=next((c for c in ('csp_id','csp_code','csp_code_new','terminal_id') if c in candidate_df.columns),None)
                        candidate_name_col=next((c for c in ('csp_name','terminal_name','name') if c in candidate_df.columns),None)
                        if candidate_id_col and candidate_name_col:
                            part=candidate_df[[candidate_id_col,candidate_name_col]].copy()
                            part.columns=['csp_id','csp_name']
                            part['csp_id']=_clean_csp_ids(part['csp_id'])
                            part['csp_name']=part['csp_name'].fillna('').astype(str).str.strip()
                            part=part[part['csp_id'].str.fullmatch(r'1A85\\d{4}',na=False) & part['csp_name'].ne('')]
                            if not part.empty:
                                if identity_crosswalk is None or identity_crosswalk.empty:
                                    identity_crosswalk=part
                                else:
                                    identity_crosswalk=pd.concat([identity_crosswalk,part],ignore_index=True)
                    except Exception:
                        continue
                if ps_name:
                    ps=excel_io.read_excel(content,sheet_name=ps_name,engine='openpyxl')
                    ps=normalize_columns(ps)
                    # Use Payment Status as the authoritative CSP ID/name crosswalk for
                    # this BC upload only. This is period-bound source evidence, not a
                    # permanent alias list.
                    id_col=next((c for c in ('csp_id','csp_code','csp_code_new','terminal_id') if c in ps.columns),None)
                    name_col=next((c for c in ('csp_name','terminal_name','name') if c in ps.columns),None)
                    if id_col and name_col:
                        identity_crosswalk=ps[[id_col,name_col]].copy()
                        identity_crosswalk.columns=['csp_id','csp_name']
                        identity_crosswalk['csp_id']=_clean_csp_ids(identity_crosswalk['csp_id'])
                        identity_crosswalk['csp_name']=identity_crosswalk['csp_name'].fillna('').astype(str).str.strip()
                        identity_crosswalk=identity_crosswalk[identity_crosswalk['csp_id'].str.fullmatch(r'1A85\d{4}',na=False) & identity_crosswalk['csp_name'].ne('')].drop_duplicates()
                    # Fallback for current BC workbooks whose identity sheet is not
                    # literally named 'Payment Status' or whose identity columns live
                    # on another sheet. This is still current-upload evidence only:
                    # collect valid canonical CSP IDs and names from this workbook,
                    # then let the roster resolver accept a mapping only when the
                    # normalized name resolves to exactly one distinct CSP ID.
                    if identity_crosswalk is None or identity_crosswalk.empty:
                        identity_frames=[]
                        for candidate_sheet in xl.sheet_names:
                            try:
                                candidate_df=excel_io.read_excel(content,sheet_name=candidate_sheet,engine='openpyxl')
                                candidate_df=normalize_columns(candidate_df)
                                candidate_id_col=next((c for c in ('csp_id','csp_code','csp_code_new','terminal_id') if c in candidate_df.columns),None)
                                candidate_name_col=next((c for c in ('csp_name','terminal_name','name') if c in candidate_df.columns),None)
                                if candidate_id_col and candidate_name_col:
                                    part=candidate_df[[candidate_id_col,candidate_name_col]].copy()
                                    part.columns=['csp_id','csp_name']
                                    part['csp_id']=_clean_csp_ids(part['csp_id'])
                                    part['csp_name']=part['csp_name'].fillna('').astype(str).str.strip()
                                    part=part[part['csp_id'].str.fullmatch(r'1A85\d{4}',na=False) & part['csp_name'].ne('')]
                                    if not part.empty:
                                        identity_frames.append(part)
                            except Exception:
                                # A malformed/unrelated sheet is not identity evidence.
                                continue
                        if identity_frames:
                            identity_crosswalk=pd.concat(identity_frames,ignore_index=True).drop_duplicates(['csp_id','csp_name'])
                    # The standard BC workbook already contains the CSP geography
                    # evidence in Payment Status.POPULATION.  It is a source field,
                    # not a rate inference.  Preserve the raw population and derive
                    # only the SBI rule grouping used by the rate engine.
                    if 'csp_id' not in ps.columns and 'csp_code' in ps.columns:
                        ps=ps.rename(columns={'csp_code':'csp_id'})
                    if 'csp_id' in ps.columns and 'population' in ps.columns:
                        geo=ps[['csp_id','population']].copy()
                        geo['csp_id']=geo['csp_id'].astype('string').str.strip().str.upper()
                        geo['population_raw']=geo['population'].astype('string').str.strip().str.upper()
                        geo=geo[geo['csp_id'].ne('') & geo['population_raw'].ne('')].copy()
                        geo['channel']=geo['population_raw'].replace({
                            'SEMI URBAN':'RURAL','SEMI-URBAN':'RURAL','SEMIURBAN':'RURAL',
                            'URBAN/METRO':'URBAN','METRO':'URBAN'
                        })
                        geo=geo[geo['channel'].isin(['RURAL','URBAN'])].copy()
                        # A CSP with conflicting geography evidence must not be
                        # assigned whichever row happens to appear first. Exclude
                        # conflicted CSPs so the financial engine keeps them
                        # explicitly unresolved until the source is corrected.
                        geo_counts=geo.groupby('csp_id')['channel'].nunique()
                        geo_conflicts=set(geo_counts[geo_counts>1].index.tolist())
                        geo=geo[~geo['csp_id'].isin(geo_conflicts)].drop_duplicates('csp_id',keep='first')
                        derived_geo=geo[['csp_id','population_raw','channel']].copy()
                        lookup=derived_geo.set_index('csp_id')['channel']
                        source_csp_col='csp_id' if 'csp_id' in df.columns else ('csp_code' if 'csp_code' in df.columns else None)
                        if source_csp_col:
                            df['channel']=df[source_csp_col].astype('string').str.strip().str.upper().map(lookup)
            except Exception as exc:
                derived_geo = None
                v_geo_note = f'Automatic CSP geography extraction was unavailable: {exc}'
            else:
                v_geo_note = None
        else:
            v_geo_note = None
        std,v=validate_commission_data(df); v=_validation_with_columns(v,std)
        if file.filename.lower().endswith('.xlsx'):
            v['workbook_source_controls']=_bc_workbook_source_controls(content, std)
        v['parser_version']=COMMISSION_PARSER_VERSION
        if not v.get('valid'):
            record_upload_failure('commission', file.filename, 'BC commission upload did not pass validation: ' + ' | '.join(map(str, v.get('errors') or v.get('missing_columns') or ['source validation failed'])))
        if v['valid']:
            # Preserve the Rural CSP master across BC-report uploads. Its month is
            # independently checked by /rural-commission, so stale evidence is never
            # silently used; it remains available if it matches the newly uploaded
            # period regardless of upload order.
            prepare_source_upload('commission',sha)
            # A replacement BC source invalidates any geography extracted from the
            # previous period. For the standard SBI workbook we immediately rebuild
            # geography from Payment Status.POPULATION, so no manual upload is needed.
            clear_source('csp_geography')
            try:
                GEO.joinpath('latest_csp_geography.csv').unlink()
            except FileNotFoundError:
                pass
            clear_cache()
            std.to_csv(CM/'latest_commission.csv',index=False)
            raw_display_df.to_csv(CM/'latest_commission_raw.csv',index=False)
            period_start,period_end=_commission_source_period_bounds(
                std['commission_date'] if 'commission_date' in std.columns else None,
                v.get('commission_date_granularity'),
            )
            extra={'validation':v,'raw_rows':int(df.attrs.get('source_physical_rows_after_header',len(df))),'source_data_rows':int(len(raw_display_df)),'blank_rows_after_header':int(df.attrs.get('blank_rows_after_header',0)),'stored_rows':len(std),'columns_stored':len(std.columns),'has_date':bool('commission_date' in std.columns and parse_date_series(std['commission_date']).notna().any()),'date_granularity':v.get('commission_date_granularity'),'workbook_source_controls':v.get('workbook_source_controls')}
            save_source('commission',file.filename,chosen,len(std),period_start,period_end,extra=extra,sha256=sha)
            # Replace identity crosswalk on every BC report upload; it is tied to the
            # current commission batch and must never survive into another period.
            if identity_crosswalk is not None and not identity_crosswalk.empty:
                # Keep repeated rows in the current BC Payment Status crosswalk.
                # Repeated CSP IDs are not inherently ambiguous: exports can repeat
                # the same CSP with the same normalized name. Resolution later maps
                # a roster name only when it identifies exactly one canonical CSP ID.
                # If one name maps to multiple IDs, the roster upload remains blocked.
                identity_crosswalk=identity_crosswalk.drop_duplicates(['csp_id','csp_name'])
                identity_crosswalk.to_csv(CSP_IDENTITY,index=False)
                cm_meta=load_metadata().get('commission') or {}
                identity_period=_month_from_text(file.filename) or _month_from_text(chosen or '')
                CSP_IDENTITY_META.write_text(json.dumps({'source':'Current BC Report identity crosswalk (Payment Status preferred; unique-ID/name sheet fallback)','filename':file.filename,'sha256':sha,'batch_id':cm_meta.get('batch_id'),'period':identity_period,'rows':int(len(identity_crosswalk))},indent=2),encoding='utf-8')
            else:
                for identity_path in (CSP_IDENTITY,CSP_IDENTITY_META):
                    try: identity_path.unlink()
                    except FileNotFoundError: pass
            # Auto-register geography as a first-class source when it came from the
            # BC workbook itself. This is stronger than asking the operator to re-key
            # the same CSP classification into a separate master.
            if derived_geo is not None and not derived_geo.empty:
                derived_geo[['csp_id','channel']].to_csv(GEO/'latest_csp_geography.csv',index=False)
                geo_validation={
                    'valid': True,
                    'source': 'BC Report / Payment Status.POPULATION',
                    'source_file': file.filename,
                    'rows': int(len(derived_geo)),
                    'unique_csp_rows': int(derived_geo['csp_id'].nunique()),
                    'conflicting_csp_count': int(len(geo_conflicts)),
                    'conflicting_csps': sorted(geo_conflicts)[:100],
                    'population_distribution': {str(k): int(v) for k,v in derived_geo['population_raw'].value_counts().to_dict().items()},
                    'rule_geography_distribution': {str(k): int(v) for k,v in derived_geo['channel'].value_counts().to_dict().items()},
                    'mapping': 'RURAL + SEMI URBAN -> RURAL; URBAN + METRO -> URBAN',
                    'no_geography_inference': True,
                    'coverage_note': 'Geography is sourced from the BC workbook Payment Status.POPULATION; no CSP geography was inferred from commission amount. Conflicting CSP geography is left unresolved rather than selecting an arbitrary row.'
                }
                save_source('csp_geography',f'{file.filename} :: Payment Status.POPULATION','Payment Status',len(derived_geo),extra={'validation':geo_validation,'derived':True,'parent_source_sha256':sha},sha256=sha)
                v['csp_geography_source']='BC Report / Payment Status.POPULATION'
                v['csp_geography_rows']=int(len(derived_geo))
                v['csp_geography_distribution']=geo_validation['population_distribution']
                if geo_conflicts:
                    v.setdefault('warnings',[]).append(f'{len(geo_conflicts)} CSP(s) have conflicting Rural/Urban evidence in Payment Status; those CSPs were left without derived geography and remain conditional for geography-dependent SBI rules.')
            elif v_geo_note:
                v.setdefault('warnings',[]).append(v_geo_note)
            _refresh_processing_snapshot()
        v['selected_sheet']=chosen; v['header_row_zero_based']=header
        return _response({'file_type':'commission','filename':file.filename,'sheet_name':chosen,'available_sheets':sheets,'saved':v['valid'],'validation':v,'columns':list(std.columns),'preview':preview_dataframe(std)})
    except HTTPException as exc:
        record_upload_failure('commission', getattr(file, 'filename', ''), str(exc.detail))
        raise
    except Exception as e:
        record_upload_failure('commission', getattr(file, 'filename', ''), str(e))
        raise HTTPException(400,str(e))

def _month_from_text(value):
    """Return YYYY-MM from an explicit month/year label without guessing a year."""
    raw=str(value or '').strip()
    if not raw:
        return None
    m=re.search(r"(?i)(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*[-_ /']*\s*(20\d{2}|\d{2})(?!\d)",raw)
    if m:
        token=m.group(1).lower()[:3]
        month={x:i for i,x in enumerate(['','jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']) if x}.get(token)
        year=int(m.group(2)); year=year+2000 if year<100 else year
        if month: return f'{year:04d}-{month:02d}'
    m=re.search(r'(?<!\d)(20\d{2})[-_/](0?[1-9]|1[0-2])(?!\d)',raw)
    if m: return f'{int(m.group(1)):04d}-{int(m.group(2)):02d}'
    return None

def _active_single_month_period():
    """Infer a supplement's period from the active successful-transactions upload.

    This fallback is used only when the supplement has no period column or period-bearing
    filename. It is safe only when the active transaction source has dates within one
    calendar month; multi-month or undated transaction sources remain explicitly ambiguous.
    """
    meta = load_metadata().get('transactions') or {}
    start = str(meta.get('period_start') or '')[:7]
    end = str(meta.get('period_end') or '')[:7]
    if re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])', start) and start == end:
        return start
    return None


def _month_bounds(period):
    if not period or not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',str(period)):
        return None,None
    year,month=map(int,period.split('-'))
    return f'{year:04d}-{month:02d}-01',f'{year:04d}-{month:02d}-{calendar.monthrange(year,month)[1]:02d}'

def _read_supplement_sheet_with_header(content, sheet_name):
    """Detect the real table header in formatted monthly workbooks with title rows."""
    preview = excel_io.read_excel(content, sheet_name=sheet_name, header=None,
                            nrows=12, engine='openpyxl')
    header_idx = 0
    for idx, row in preview.iterrows():
        cells = [re.sub(r'[^a-z0-9]+', '_', str(v).strip().lower()).strip('_')
                 for v in row.tolist() if not pd.isna(v)]
        has_csp = any(c in {'csp_code','csp_code_new','csp_id','csp_id_code'} or
                      c.startswith('csp_code_') for c in cells)
        has_data_header = any(('pmjjby' in c or 'pmsby' in c or 'passbook' in c or
                               c in {'count','prints','transactions','csp_name'})
                              for c in cells)
        if has_csp and has_data_header:
            header_idx = idx
            break
    return excel_io.read_excel(content, sheet_name=sheet_name, header=header_idx,
                         engine='openpyxl')


def _normalized_supplement_df(content, filename, sheet_name=None):
    if filename.lower().endswith('.xlsx'):
        xl=excel_io.excel_file(content)
        chosen=sheet_name if sheet_name in xl.sheet_names else xl.sheet_names[0]
        raw=_read_supplement_sheet_with_header(content, chosen)
    else:
        chosen=None
        raw=pd.read_csv(BytesIO(content),low_memory=False)
    raw.columns=(raw.columns.astype(str).str.strip().str.lower().str.replace(r'[^a-z0-9]+','_',regex=True).str.strip('_'))
    return raw,chosen

def _alias_columns(df, alias_map):
    ren={}
    for dest,candidates in alias_map.items():
        for c in candidates:
            if c in df.columns:
                ren[c]=dest; break
    return df.rename(columns=ren),ren

def _read_supplement_sheets(content, filename, requested_sheet=None):
    """Read the requested sheet or all sheets in an XLSX supplement."""
    if filename.lower().endswith('.xlsx'):
        xl=excel_io.excel_file(content)
        names=[requested_sheet] if requested_sheet in xl.sheet_names else xl.sheet_names
        return [(name,_read_supplement_sheet_with_header(content,name)) for name in names if name]
    return [(None,pd.read_csv(BytesIO(content),low_memory=False))]

def _clean_supplement_columns(raw):
    raw=raw.copy()
    raw.columns=(raw.columns.astype(str).str.strip().str.lower().str.replace(r'[^a-z0-9]+','_',regex=True).str.strip('_'))
    # Excel exports sometimes include duplicate header labels; pandas may suffix them.
    return raw

def _clean_csp_ids(series):
    # Keep identifiers as strings and normalize Excel numeric/whitespace artifacts.
    return series.map(lambda v: '' if pd.isna(v) else re.sub(r'\.0$','',str(v).strip().upper()))

def _month_columns(df):
    return [(c,_month_from_text(c)) for c in df.columns if _month_from_text(c)]

def _passbook_count_column(columns):
    """Choose a count column, never a status/availability column such as 'Passbook Printer Status'."""
    candidates=[]
    for c in columns:
        name=str(c).strip().lower()
        if 'passbook' not in name or 'print' not in name:
            continue
        if any(token in name for token in ('status','available','availability','printer_yes','printer_no')):
            continue
        has_count_word=any(token in name for token in ('count','prints','no_of_prints','number_of_prints'))
        has_month=_month_from_text(name) is not None
        if has_count_word or has_month:
            candidates.append((c, 0 if has_count_word else 1))
    return min(candidates, key=lambda item:item[1])[0] if candidates else None

@router.post('/social-security-counts')
async def social_security_counts(file:UploadFile=File(...),sheet_name:Optional[str]=Form(None)):
    """Upload PMJJBY/PMSBY evidence in long form or scheme-specific month-column sheets."""
    try:
        content,sha=await _read(file,sheet_name,'social_security_counts')
        frames=[]; mapped_all={}; selected=[]
        excluded_non_csp_rows = 0
        for chosen,source in _read_supplement_sheets(content,file.filename,sheet_name):
            raw=_clean_supplement_columns(source)
            # Support the official CSP-wise monthly summary layout where PMJJBY
            # and PMSBY counts are separate columns (e.g. "PMJJBY done",
            # "PMSBY done"), rather than separate sheets or a scheme/count pair.
            scheme_count_cols = []
            for col in raw.columns:
                norm = re.sub(r'[^a-z0-9]+', '_', str(col).strip().lower()).strip('_')
                if 'pmjjby' in norm and any(k in norm for k in ('done','count','completed','transaction')):
                    scheme_count_cols.append((col, 'PMJJBY'))
                elif 'pmsby' in norm and any(k in norm for k in ('done','count','completed','transaction')):
                    scheme_count_cols.append((col, 'PMSBY'))
            csp_col = next((c for c in raw.columns if c in {'csp_id','csp_code','csp_code_new','csp','csp_id_code'}), None)
            if csp_col and scheme_count_cols and not any(c in raw.columns for c in ('count','txn_count','transaction_count','successful_transactions','transactions','number_of_transactions')):
                period_from_file = _month_from_text(file.filename)
                for count_col, scheme in scheme_count_cols:
                    wide = pd.DataFrame({
                        'csp_id': raw[csp_col],
                        'transaction_type': scheme,
                        'count': pd.to_numeric(raw[count_col], errors='coerce'),
                        'period': period_from_file,
                        'premium': pd.NA,
                    })
                    wide = wide[wide['count'].notna() & wide['count'].gt(0)]
                    if not wide.empty and period_from_file:
                        frames.append(wide[['csp_id','transaction_type','count','premium','period']].copy())
                        mapped_all[str(chosen or 'CSV')] = {'csp_id': csp_col, f'{scheme.lower()}_count': count_col}
                        if chosen and chosen not in selected: selected.append(chosen)
                continue
            df,mapped=_alias_columns(raw,{
                'csp_id':['csp_id','csp_code','csp_code_new','csp','csp_id_code'],
                'transaction_type':['transaction_type','scheme','product','scheme_type','sheet_name'],
                'count':['count','txn_count','transaction_count','successful_transactions','transactions','number_of_transactions'],
                'premium':['premium','premium_amount','amount','premium_value'],
                'period':['period','month','transaction_month','report_month']})
            if 'csp_id' not in df.columns:
                # Skip cover/summary sheets, but not a selected sheet.
                if sheet_name: raise HTTPException(400,'Selected PMJJBY/PMSBY sheet is missing CSP Code/CSP ID.')
                continue
            if 'transaction_type' not in df.columns and chosen and chosen.strip().upper() in {'PMJJBY','PMSBY'}:
                df['transaction_type']=chosen.strip().upper()
            if 'count' not in df.columns:
                months=_month_columns(df)
                if months:
                    id_cols=[c for c in df.columns if c not in {n for n,_ in months}]
                    pieces=[]
                    for col,period in months:
                        piece=df[id_cols].copy(); piece['count']=df[col]; piece['period']=period; pieces.append(piece)
                    df=pd.concat(pieces,ignore_index=True)
                else:
                    continue
            elif 'period' not in df.columns:
                period=_month_from_text(file.filename)
                if period: df['period']=period
            if 'premium' not in df.columns:
                # Premium may be absent from the CSP count source; retain evidence as unknown,
                # but only permit it when source explicitly contains premium evidence.
                df['premium']=pd.NA
            if 'period' not in df.columns:
                period=_month_from_text(file.filename)
                if period: df['period']=period
            if 'period' not in df.columns: continue
            if 'transaction_type' not in df.columns: continue
            df['csp_id']=_clean_csp_ids(df['csp_id'])
            # CSP identity must come from the current-period source or an explicitly
            # uploaded/approved current-period identity crosswalk. Never carry forward
            # a name-to-ID correction inferred from a prior month's report.
            df['transaction_type']=df['transaction_type'].astype(str).str.strip().str.upper().replace({
                'PRADHAN MANTRI JEEVAN JYOTI BIMA YOJANA':'PMJJBY',
                'PRADHAN MANTRI SURAKSHA BIMA YOJANA':'PMSBY',
                'PM JEEVAN JYOTI BIMA YOJANA':'PMJJBY','PM SURAKSHA BIMA YOJANA':'PMSBY'})
            df['count']=pd.to_numeric(df['count'],errors='coerce')
            df['premium']=pd.to_numeric(df['premium'],errors='coerce')
            df['period']=df['period'].map(lambda x: (str(x).strip() if re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',str(x).strip()) else _month_from_text(x)))
            # Drop empty/footer rows, but never silently drop a populated invalid CSP row.
            # Scheme count sheets often list CSPs with a blank count for that scheme;
            # those are non-activity rows, not invalid transactions. Ignore blank counts.
            df=df[df['count'].notna() & df['count'].gt(0)].copy()
            if df.empty: continue
            # The approved commission is count × period-specific rate; some official CSP-wise
            # scheme workbooks provide counts but no premium column. Accept those counts without
            # inventing premium/transaction amount, and expose the evidence gap in validation.
            # Non-CSP labels such as names/totals can appear below the source table.
            # Exclude those rows, but reject malformed IDs that purport to be CSP codes.
            non_csp=~df['csp_id'].str.startswith('1A85',na=False)
            excluded_non_csp_rows += int(non_csp.sum())
            df=df[~non_csp].copy()
            invalid=~df['csp_id'].str.match(r'^1A85\d{4}$',na=False) | ~df['transaction_type'].isin(['PMJJBY','PMSBY']) | df['count'].isna() | df['count'].le(0) | df['premium'].lt(0) | df['period'].isna()
            if invalid.any():
                raise HTTPException(400,f'PMJJBY/PMSBY source has {int(invalid.sum())} invalid populated row(s). Check CSP IDs, scheme, positive count and period. If the workbook has separate PMJJBY/PMSBY sheets, upload both sheets together without selecting only one.')
            frames.append(df[['csp_id','transaction_type','count','premium','period']].copy())
            mapped_all[str(chosen or 'CSV')]=mapped
            selected.append(chosen or 'CSV')
        if not frames:
            raise HTTPException(400,'No PMJJBY/PMSBY data rows found. Expected CSP Code and either Count + Period or a month-year count column, with scheme identifiable from a column or sheet name and premium evidence.')
        out=pd.concat(frames,ignore_index=True).drop_duplicates()
        out['source_file']=file.filename
        out.groupby(['csp_id','transaction_type','premium','period'],as_index=False,dropna=False)['count'].sum().to_csv(SOCIAL_COUNTS,index=False)
        # Unresolved CSP identity exceptions are preserved; only a current-period
        # authoritative crosswalk may resolve them.
        periods=sorted(out['period'].unique().tolist()); start=_month_bounds(periods[0])[0] if len(periods)==1 else None; end=_month_bounds(periods[0])[1] if len(periods)==1 else None
        validation={'valid':True,'rows':len(out),'periods':periods,'mapped_columns':mapped_all,'sheets_read':selected,'premium_evidence':'PRESENT' if out['premium'].notna().all() else 'NOT_PROVIDED_IN_SOURCE','premium_missing_rows':int(out['premium'].isna().sum()),'non_csp_summary_rows_excluded':int(excluded_non_csp_rows),'manual_csp_mappings':{},'manual_csp_mapped_rows':0,'commission_calculation':'count × approved period-specific commission rate; premium is not inferred','parser_version':'62.6.106-period-agnostic-social-security-no-stale-alias'}
        save_source('social_security_counts',file.filename,','.join(selected),len(out),start,end,extra={'validation':validation},sha256=sha)
        clear_cache()
        return _response({'file_type':'social_security_counts','filename':file.filename,'sheet_name':','.join(selected),'saved':True,'validation':validation})
    except HTTPException: raise
    except Exception as e: raise HTTPException(400,f'PMJJBY/PMSBY upload failed: {e}')

@router.post('/passbook-printing-counts')
async def passbook_printing_counts(file:UploadFile=File(...),sheet_name:Optional[str]=Form(None)):
    """Upload CSP-wise passbook counts in long form or month-column wide form."""
    try:
        content,sha=await _read(file,sheet_name,'passbook_printing_counts')
        raw,chosen=_normalized_supplement_df(content,file.filename,sheet_name)
        # Monthly source workbooks often name the count column "Passbook prints Sep"
        # (month is in the header, while the year is in the filename), which cannot
        # be matched by an exact static alias. Map that explicit print-count column
        # to count; period still comes from the current upload filename/header.
        dynamic_print_count = _passbook_count_column(raw.columns)
        if dynamic_print_count and not any(c in raw.columns for c in
                ('count','print_count','prints','passbook_prints','source_count','count_prints','no_of_prints','number_of_prints')):
            raw=raw.rename(columns={dynamic_print_count:'count'})
        raw,mapped=_alias_columns(raw,{
            'csp_id':['csp_id','csp_code','csp_code_new','csp','csp_id_code','csp_code_id'],
            'count':['count','print_count','prints','passbook_prints','source_count','count_prints','no_of_prints','number_of_prints'],
            'period':['period','month','transaction_month','report_month'],
            'population':['population','area','channel','geography'],
            'rate':['rate','commission_rate','rate_per_print']})
        if 'csp_id' not in raw.columns:
            raise HTTPException(400,'Passbook source is missing CSP Code/CSP ID. Recognized headers include CSP Code, CSP ID and CSP Code New.')
        if 'count' not in raw.columns:
            month_cols=_month_columns(raw)
            if not month_cols:
                raise HTTPException(400,'Passbook source must have a Count/Prints column plus Period, or one or more month-year count columns (for example August 2026).')
            id_cols=[c for c in raw.columns if c not in {name for name,_ in month_cols}]
            pieces=[]
            for count_col,period in month_cols:
                piece=raw[id_cols].copy(); piece['count']=raw[count_col]; piece['period']=period; pieces.append(piece)
            raw=pd.concat(pieces,ignore_index=True)
        elif 'period' not in raw.columns:
            period=_month_from_text(file.filename) or _active_single_month_period()
            if not period: raise HTTPException(400,'Passbook period is ambiguous: add a Period column, include month/year in the filename, or upload a dated single-month Successful Transactions Report first.')
            raw['period']=period
        else:
            raw['period']=raw['period'].map(lambda x: (str(x).strip() if re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',str(x).strip()) else _month_from_text(x)))
        # A footer such as 'TOTAL' is a sum of the rows above, not a CSP: counting it doubles the prints.
        raw=raw[~raw['csp_id'].astype(str).str.strip().str.upper().isin({'TOTAL','GRAND TOTAL','SUBTOTAL','OVERALL TOTAL'})].copy()
        raw['csp_id']=_clean_csp_ids(raw['csp_id'])
        # CSP identity must come from the current-period source. No prior-month
        # name-to-ID correction is applied to current uploads.
        raw['count']=pd.to_numeric(raw['count'],errors='coerce')
        raw['transaction_type']='PASSBOOK PRINTING'
        if 'population' not in raw.columns: raw['population']=''
        if 'rate' not in raw.columns: raw['rate']=pd.NA
        # Ignore blank rows and summary/footer rows with no positive count. Preserve
        # populated rows with malformed CSP IDs as explicit exceptions; never silently
        # drop them or fuzzy-map a CSP name to an ID. Valid CSP rows continue through
        # the count control while unresolved rows remain visible for manual correction.
        raw=raw[raw['count'].notna() & raw['count'].gt(0)].copy()
        valid_id=raw['csp_id'].str.match(r'^1A85\d{4}$',na=False)
        valid_period=raw['period'].notna() & raw['period'].astype(str).str.match(r'^20\d{2}-(0[1-9]|1[0-2])$',na=False)
        valid=valid_id & valid_period
        exception_rows=raw.loc[~valid,['csp_id','count','period']].copy()
        if not exception_rows.empty:
            exception_rows['source_file']=file.filename
            exception_rows['reason']=exception_rows.apply(lambda r: 'INVALID_OR_MISSING_CSP_CODE' if not re.fullmatch(r'1A85\d{4}',str(r['csp_id'] or '').strip().upper()) else 'INVALID_OR_MISSING_PERIOD',axis=1)
            exception_rows.to_csv(PASSBOOK_EXCEPTIONS,index=False)
        else:
            PASSBOOK_EXCEPTIONS.unlink(missing_ok=True)
        raw=raw.loc[valid].copy()
        if raw.empty:
            raise HTTPException(400,'Passbook source has no valid CSP-coded rows for reconciliation. Populated invalid rows were preserved as exceptions; correct CSP Code and re-upload.')
        out=raw[['csp_id','transaction_type','count','population','rate','period']].copy(); out['source_file']=file.filename
        out.to_csv(PASSBOOK_COUNTS,index=False)
        periods=sorted(out['period'].unique().tolist()); start=_month_bounds(periods[0])[0] if len(periods)==1 else None; end=_month_bounds(periods[-1])[1] if len(periods)==1 else None
        validation={'valid':True,'rows':len(out),'periods':periods,'mapped_columns':mapped,'geography_source':'Current BC commission workbook POPULATION; supplemental population/rate ignored for calculation','invalid_populated_rows_preserved_as_exceptions':int(len(exception_rows)),'exception_count':int(len(exception_rows)),'exception_print_count':int(pd.to_numeric(exception_rows['count'],errors='coerce').fillna(0).sum()) if not exception_rows.empty else 0,'exception_file':PASSBOOK_EXCEPTIONS.name if not exception_rows.empty else None,'manual_csp_mappings':{},'manual_csp_mapped_rows':0,'parser_version':'62.6.127-passbook-printer-actual-amount-fix'}
        save_source('passbook_printing_counts',file.filename,chosen,len(out),start,end,extra={'validation':validation},sha256=sha)
        clear_cache()
        return _response({'file_type':'passbook_printing_counts','filename':file.filename,'sheet_name':chosen,'saved':True,'validation':validation})
    except HTTPException: raise
    except Exception as e: raise HTTPException(400,f'Passbook printing upload failed: {e}')

@router.post('/rural-csp')
async def rural_csp(file:UploadFile=File(...)):
    try:
        content,sha=await _read(file,None,'rural_csp')
        meta=load_metadata().get('rural_csp') or {}
        if meta.get('sha256') == sha and RURAL_MASTER_PATH.exists():
            v=meta.get('validation') or {}
            return _response({'file_type':'rural_csp','filename':file.filename,'saved':bool(v.get('valid')),'validation':v,'cached':True})
        # A failed replacement must never leave the previous period silently
        # active. Invalidate the old Rural source before validating the new file.
        clear_source('rural_csp')
        try:
            RURAL_MASTER_PATH.unlink()
        except FileNotFoundError:
            pass
        std,v=(parse_rural_csp_csv(content,file.filename) if file.filename.lower().endswith(".csv") else parse_rural_csp_workbook(content,file.filename))
        if not v.get('valid'):
            raise ValueError('Rural CSP source validation failed.')
        save_rural_master(std)
        save_source('rural_csp',file.filename,v.get('sheet_name'),len(std),v.get('period_start'),v.get('period_end'),extra={'validation':v,'period':v.get('period'),'parser_version':v.get('parser_version')},sha256=sha)
        clear_cache()
        return _response({'file_type':'rural_csp','filename':file.filename,'sheet_name':v.get('sheet_name'),'saved':True,'validation':v,'columns':list(std.columns)})
    except HTTPException: raise
    except Exception as e:
        # Make the common wrong-file selection actionable without accepting an
        # unrelated permanent rules workbook as a period-specific eligibility roster.
        message = str(e)
        if 'could not find rural csp sheet' in message.lower() and 'expected_commission_rule' in file.filename.lower():
            message = ('The selected file appears to be the permanent SBI Expected Commission Rule workbook, not the Rural CSP Eligibility List. '
                       'Upload the current-period Rural CSP roster containing CSP ID and a month-labelled Total Login Day column (for example, Total Login Day Aug-26).')
        raise HTTPException(400,f'Rural CSP upload failed: {message}')

@router.post('/rural_csp')
async def rural_csp_compat(file:UploadFile=File(...)):
    """Backward-compatible alias for clients that used the normalized source key."""
    return await rural_csp(file)

@router.post('/csp-geography')
async def csp_geography(file:UploadFile=File(...),sheet_name:Optional[str]=Form(None)):
    try:
        content,sha=await _read(file,sheet_name,'csp_geography')
        cached=_cached_response('csp_geography',file.filename,sha)
        if cached:
            old=load_metadata().get('csp_geography') or {}
            save_source('csp_geography',file.filename,old.get('sheet_name'),old.get('rows',0),extra={'validation':cached.get('validation',{})},sha256=sha)
            return _response(cached)
        from io import BytesIO
        df=excel_io.read_excel(content,sheet_name=sheet_name,engine='openpyxl') if file.filename.lower().endswith('.xlsx') else pd.read_csv(BytesIO(content))
        df.columns=(df.columns.astype(str).str.strip().str.lower().str.replace(r'[^a-z0-9]+','_',regex=True).str.strip('_'))
        aliases={'csp_id':['csp_code','csp_id','csp','csp_code_new'],'channel':['geography','channel','location_type','area_type']}
        ren={};
        for dest,cands in aliases.items():
            for c in cands:
                if c in df.columns: ren[c]=dest; break
        df=df.rename(columns=ren)
        missing=[c for c in ('csp_id','channel') if c not in df.columns]
        if missing: raise HTTPException(400,'CSP geography master is missing required columns: '+', '.join(missing))
        df['csp_id']=df['csp_id'].astype(str).str.strip().str.upper(); df['channel']=df['channel'].astype(str).str.strip().str.upper().replace({'SEMI URBAN':'RURAL','SEMI-URBAN':'RURAL','METRO':'URBAN','URBAN/METRO':'URBAN'})
        invalid=sorted(set(df.loc[~df['channel'].isin(['RURAL','URBAN']),'channel'].dropna().tolist()))
        dup=int(df['csp_id'].duplicated(keep=False).sum())
        valid=df['csp_id'].ne('') & df['channel'].isin(['RURAL','URBAN'])
        validation={'valid':not missing and not invalid and dup==0 and int(valid.sum())==len(df),'rows':len(df),'processable_rows':int(valid.sum()),'missing_columns':missing,'invalid_geography_values':invalid,'duplicate_csp_rows':dup,'mapped_columns':ren}
        if not validation['valid']: raise HTTPException(400,'CSP geography validation failed: '+str(validation))
        df[['csp_id','channel']].to_csv(GEO/'latest_csp_geography.csv',index=False)
        clear_cache()
        save_source('csp_geography',file.filename,sheet_name,len(df),extra={'validation':validation},sha256=sha)
        return _response({'file_type':'csp_geography','filename':file.filename,'saved':True,'validation':validation})
    except HTTPException: raise
    except Exception as e: raise HTTPException(400,f'CSP geography upload failed: {e}')

@router.post('/rate-master')
async def rate_master(file:UploadFile=File(...),sheet_name:Optional[str]=Form(None)):
    """The SBI rule master is bundled permanently; monthly upload replacement is disabled."""
    raise HTTPException(
        409,
        'SBI Expected Commission Rule is a permanent bundled master and must not be re-uploaded monthly. '
        'Only current-period transaction, BC commission, and applicable supplemental evidence should be uploaded. '
        'A genuine SBI rule change must be introduced through a versioned project release.'
    )
    try:
        content,sha=await _read(file,sheet_name,'rate_master')
        cached=_cached_response('rate_master',file.filename,sha)
        if cached:
            prepare_source_upload('rate_master',sha)
            old=load_metadata().get('rate_master') or {}
            save_source('rate_master',file.filename,old.get('sheet_name'),old.get('rows',0),old.get('period_start'),old.get('period_end'),extra={'rules':old.get('rules',old.get('rows',0)),'transaction_types':old.get('transaction_types',0),'validation':cached.get('validation',{})},sha256=sha)
            _refresh_processing_snapshot()
            return _response(cached)
        # CSV uploads are supported only when they already express a normalized
        # rule table (transaction_type + rate, with optional scope/status/slab
        # fields). Do not try to open CSV bytes as an Excel ZIP container.
        if file.filename.lower().endswith('.csv'):
            from io import BytesIO
            from app.services.rate_master import validate_rate_master
            raw_csv = pd.read_csv(BytesIO(content), low_memory=False)
            std, v = validate_rate_master(raw_csv)
            chosen = 'CSV rule master'
            sheets = []
            v['source_workbook_type'] = 'Normalized CSV rule master'
            v['selected_sheet'] = chosen
            v['columns'] = list(std.columns)
        else:
            # SBI rate workbooks are multi-sheet commercial masters. Read the
            # complete workbook (primary commission sheet + slab schedules) so a
            # slab-based product is never reduced to an average/inferred rate.
            std,v=build_rate_master_from_workbook(content,file.filename,sheet_name)
            chosen=v.get('selected_sheet')
            sheets=v.get('available_sheets',[])
            v['columns']=list(std.columns)
            v['header_row_zero_based']=2 if v.get('source_workbook_type')=='SBI structured commission/slab master' and v.get('selected_sheet')=='Table 1' else 3
        v['parser_version']=RATE_MASTER_PARSER_VERSION
        if v['valid']:
            from app.services.rate_master import apply_confirmed_remittance_reference_rules
            std=apply_confirmed_remittance_reference_rules(std)
            from app.services.rate_master import apply_sbi_pdf_schedule_rules
            std=apply_sbi_pdf_schedule_rules(std)
            clear_cache()
            std.to_csv(RM/'latest_rate_master.csv',index=False)
            save_source('rate_master',file.filename,chosen,len(std),extra={'rules':len(std),'transaction_types':int(std['transaction_type'].nunique()) if 'transaction_type' in std else 0,'validation':v},sha256=sha)
            # Preserve the original consolidated SBI rule workbook as a first-class
            # source sheet, separate from the normalized executable rule table.
            if file.filename.lower().endswith('.xlsx'):
                try:
                    xl_original = excel_io.excel_file(content)
                    consolidated_sheet = next((nm for nm in xl_original.sheet_names if str(nm).strip().upper() == 'CONSOLIDATED COMMISSION MASTER'), None)
                    if consolidated_sheet:
                        EXPECTED_RULE_DIR.mkdir(parents=True, exist_ok=True)
                        EXPECTED_RULE_PATH.write_bytes(content)
                        save_source('expected_commission_rule', file.filename, consolidated_sheet, int(v.get('rows') or len(std)),
                                    extra={'available_sheets': xl_original.sheet_names, 'validation': v, 'rules': int(v.get('rules') or len(std))}, sha256=sha)
                except Exception:
                    # The normalized approved rules remain saved; source viewer reports
                    # the prior original workbook if preserving this optional copy fails.
                    pass
            _refresh_processing_snapshot()
        return _response({'file_type':'rate_master','filename':file.filename,'sheet_name':chosen,'available_sheets':sheets,'saved':v['valid'],'validation':v,'columns':list(std.columns),'preview':preview_dataframe(std)})
    except HTTPException: raise
    except Exception as e: raise HTTPException(400,str(e))


@router.post('/expected-commission-rule')
async def expected_commission_rule(file:UploadFile=File(...),sheet_name:Optional[str]=Form(None)):
    """Upload the consolidated SBI expected-commission rule workbook.

    This updates the active deterministic rate master and preserves the original
    workbook for the dedicated source-data view.
    """
    if not file.filename.lower().endswith('.xlsx'):
        raise HTTPException(400, 'SBI Expected Commission Rule must be an XLSX workbook containing Consolidated Commission Master and/or Slabs & Incentive Matrices.')
    return await rate_master(file, sheet_name)


@router.post('/women-csp-roster')
async def women_csp_roster(file:UploadFile=File(...),sheet_name:Optional[str]=Form(None)):
    """Upload current-period Women CSP eligibility roster; SBI Rule 24 remains permanent and month-independent."""
    try:
        content,sha=await _read(file,sheet_name,'women_csp_roster')
        frames=[]; mapped_all={}; selected=[]; periods=set()
        if file.filename.lower().endswith('.xlsx'):
            xl=excel_io.excel_file(content)
            names=[sheet_name] if sheet_name in xl.sheet_names else xl.sheet_names
            sheets=[(nm,excel_io.read_excel(content,sheet_name=nm,engine='openpyxl')) for nm in names]
        else:
            sheets=[(None,pd.read_csv(BytesIO(content),low_memory=False))]
        for chosen,source in sheets:
            raw=_clean_supplement_columns(source)
            # Identify month-specific transaction-count columns without hardcoding August.
            count_candidates=[c for c in raw.columns if ('transaction_count' in c or 'txn_count' in c) and ('total' in c or 'aug' in c or 'sep' in c or 'oct' in c or 'nov' in c or 'dec' in c or 'jan' in c or 'feb' in c or 'mar' in c or 'apr' in c or 'may' in c or 'jun' in c or 'jul' in c)]
            alias_map={
                'csp_id':['csp_id','csp_code','csp_code_new','csp','csp_id_code','terminal_id'],
                'csp_name':['csp_name','name','terminal_name'],
                'transaction_count':['transaction_count','total_transaction_count','txn_count','total_txn_count'],
                'period':['period','month','month_year','report_month'],
                'terminal_status':['terminal_status','status','activity_status'],
                'population':['population','area','geography'],
            }
            if count_candidates and not any(c in raw.columns for c in alias_map['transaction_count']):
                # Use the one count column belonging to this source period; multiple period columns must be uploaded one period at a time.
                if len(count_candidates)>1:
                    raise HTTPException(400,f'Women CSP roster has multiple month-specific transaction-count columns: {count_candidates}. Upload/select one period at a time.')
                raw=raw.rename(columns={count_candidates[0]:'transaction_count'})
                count_col=count_candidates[0]
            else:
                count_col=None
            df,mapped=_alias_columns(raw,alias_map)
            if 'csp_id' not in df.columns or 'transaction_count' not in df.columns:
                if sheet_name: raise HTTPException(400,'Selected Women CSP sheet must contain CSP ID and month-specific Total Transaction Count.')
                continue
            if 'csp_name' not in df.columns: df['csp_name']=''
            if 'period' not in df.columns:
                p=_month_from_text(count_col or '') or _month_from_text(chosen or '') or _month_from_text(file.filename)
                if p: df['period']=p
            if 'period' not in df.columns:
                raise HTTPException(400,'Women CSP roster period could not be identified. Include a month-year in the transaction-count column, sheet name, or filename.')
            df['period']=df['period'].map(lambda x: (str(x).strip() if re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',str(x).strip()) else _month_from_text(x)))
            df['csp_id']=_clean_csp_ids(df['csp_id'])
            df['csp_name']=df['csp_name'].fillna('').astype(str).str.strip()
            df['transaction_count']=pd.to_numeric(df['transaction_count'],errors='coerce')
            # Drop blank/footer rows only; populated records with invalid counts are rejected.
            populated=df['csp_id'].ne('') | df['csp_name'].ne('')
            df=df[populated].copy()
            invalid=df['transaction_count'].isna() | df['transaction_count'].lt(0) | df['period'].isna()
            if invalid.any():
                raise HTTPException(400,f'Women CSP roster has {int(invalid.sum())} populated row(s) with invalid transaction count/period.')
            df['period']=df['period'].astype(str)
            periods.update(df['period'].unique().tolist())
            if 'terminal_status' not in df.columns: df['terminal_status']=''
            if 'population' not in df.columns: df['population']=''
            df['source_name']=file.filename
            frames.append(df[['csp_id','csp_name','transaction_count','period','terminal_status','population','source_name']])
            mapped_all[str(chosen or 'CSV')]=mapped
            selected.append(chosen or 'CSV')
        if not frames:
            raise HTTPException(400,'No Women CSP roster rows found. Required fields: CSP ID, CSP name (recommended), and the selected month’s total transaction count.')
        if len(periods)!=1:
            raise HTTPException(400,f'Women CSP roster must contain exactly one period; found {sorted(periods)}.')
        out=pd.concat(frames,ignore_index=True)
        # Resolve non-canonical roster IDs only through the current-period BC Report
        # Payment Status identity crosswalk. No hardcoded CSP aliases or prior-month
        # roster data are consulted. A name must map to exactly one canonical CSP ID.
        aliases={}
        mapped_rows=0
        identity_meta={}
        if CSP_IDENTITY.exists() and CSP_IDENTITY_META.exists():
            try:
                identity_meta=json.loads(CSP_IDENTITY_META.read_text(encoding='utf-8'))
                current_meta=load_metadata().get('commission') or {}
                identity_period=identity_meta.get('period')
                # Bind identity evidence to the exact currently uploaded BC workbook,
                # not to the global active_batch_id. Other legitimate uploads can
                # advance active_batch_id without replacing the BC report; requiring
                # active_batch_id equality made valid Payment Status identities fail
                # to resolve (e.g. roster ID 'OTHER ISSUE' for Sample Agent).
                # The crosswalk must still match both the commission batch and file
                # SHA-256, and any detected month must match the roster period.
                current_bc_sha=str(current_meta.get('sha256') or '')
                # The crosswalk file is replaced atomically on every valid BC upload
                # and is cryptographically bound to that exact workbook. Batch IDs
                # can legitimately advance during supplemental uploads, so SHA-256
                # is the authoritative freshness check. Normalize month strings
                # before comparing (e.g. Aug-26 vs 2026-08); reject only a real
                # period conflict, not a formatting difference.
                def _period_key(value):
                    value=str(value or '').strip()
                    if re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])', value):
                        return value
                    return _month_from_text(value)
                roster_period=next(iter(periods))
                crosswalk_period=_period_key(identity_period)
                roster_period_key=_period_key(roster_period)
                crosswalk_is_current=(
                    bool(current_bc_sha)
                    and identity_meta.get('sha256') == current_bc_sha
                    and (not crosswalk_period or not roster_period_key or crosswalk_period == roster_period_key)
                )
                if crosswalk_is_current:
                    cw=pd.read_csv(CSP_IDENTITY,dtype=str).fillna('')
                    def _name_key(value):
                        # Normalize whitespace, punctuation and case consistently for
                        # the roster and the current-period BC identity evidence.
                        return re.sub(r'[^A-Z0-9]','',str(value or '').upper())
                    # Build the resolver from the saved current BC crosswalk, and also
                    # supplement it from the raw sheet selected by the same successful
                    # BC upload. Some real BC exports put CSP_CODE/CSP_NAME on the
                    # transaction-type sheet while Payment Status headers differ. The
                    # raw file is only accepted when it belongs to the current uploaded
                    # commission SHA; no prior-month or hardcoded aliases are used.
                    frames=[cw]
                    raw_path=CM/'latest_commission_raw.csv'
                    if current_bc_sha and raw_path.exists():
                        try:
                            raw_cw=pd.read_csv(raw_path,dtype=str).fillna('')
                            raw_cw=normalize_columns(raw_cw)
                            raw_id=next((c for c in ('csp_id','csp_code','csp_code_new','terminal_id') if c in raw_cw.columns),None)
                            raw_name=next((c for c in ('csp_name','terminal_name','name') if c in raw_cw.columns),None)
                            if raw_id and raw_name:
                                raw_part=raw_cw[[raw_id,raw_name]].copy()
                                raw_part.columns=['csp_id','csp_name']
                                frames.append(raw_part)
                        except Exception:
                            # Keep the authoritative crosswalk; malformed raw rows are
                            # not identity evidence.
                            pass
                    cw=pd.concat(frames,ignore_index=True).fillna('').drop_duplicates()
                    by_name={}
                    for _,cr in cw.iterrows():
                        cid=_clean_csp_ids(pd.Series([cr.get('csp_id','')])).iloc[0]
                        key=_name_key(cr.get('csp_name',''))
                        if re.fullmatch(r'1A85\d{4}',str(cid)) and key:
                            by_name.setdefault(key,set()).add(str(cid))
                    for idx,row in out.iterrows():
                        cid=str(row.get('csp_id','')).strip().upper()
                        if re.fullmatch(r'1A85\d{4}',cid): continue
                        key=_name_key(row.get('csp_name',''))
                        candidates=by_name.get(key,set()) if key else set()
                        if len(candidates)==1:
                            resolved=next(iter(candidates))
                            out.at[idx,'csp_id']=resolved
                            aliases[f'{cid} | {row.get("csp_name", "")}']=resolved
                            mapped_rows+=1
            except Exception:
                # Fail closed below with the unresolved IDs; never guess.
                pass
        invalid_ids=~out['csp_id'].str.fullmatch(r'1A85\d{4}',na=False)
        if invalid_ids.any():
            examples=out.loc[invalid_ids,['csp_id','csp_name']].head(8).to_dict('records')
            if not (CM/'latest_commission_raw.csv').exists():
                # The usual cause: the roster was uploaded before the BC Commission Report (V62.6.212).
                raise HTTPException(400,f'No BC Commission Report is uploaded yet, so {len(examples)} roster CSP(s) without an official CSP ID cannot be identified: {examples}. Upload the BC Commission Report of this month first (Step 2), then upload this Women CSP roster again.')
            raise HTTPException(400,f'Women CSP roster has unresolved CSP IDs: {examples}. Upload the current-period BC Commission workbook first and ensure it contains canonical CSP ID and CSP Name columns. A non-canonical roster ID is resolved only when the name maps to exactly one valid CSP ID in that current workbook; the system will not guess or use prior-month data.')
        if out['csp_id'].duplicated().any():
            dups=out.loc[out['csp_id'].duplicated(keep=False),'csp_id'].unique().tolist()[:10]
            raise HTTPException(400,f'Women CSP roster contains duplicate CSP IDs after alias correction: {dups}.')
        out.to_csv(WOMEN_COUNTS,index=False)
        period=next(iter(periods))
        meta={'filename':file.filename,'sha256':sha,'sheet_name':','.join(selected),'period':period,'periods':[period], 'rows':len(out),'mapped_columns':mapped_all,'approved_alias_mappings':aliases,'alias_mapped_rows':mapped_rows,'parser_version':'women-csp-roster-v4-current-workbook-identity-sheet-discovery'}
        WOMEN_META.write_text(json.dumps(meta,indent=2),encoding='utf-8')
        save_source('women_csp_roster',file.filename,','.join(selected),len(out),f'{period}-01',None,extra={'validation':meta},sha256=sha)
        clear_cache()
        return _response({'file_type':'women_csp_roster','filename':file.filename,'sheet_name':','.join(selected),'saved':True,'validation':{'valid':True,'rows':len(out),'periods':[period],'mapped_columns':mapped_all,'approved_alias_mappings':aliases,'alias_mapped_rows':mapped_rows,'note':'Rule 24 is permanent and month-independent; only the roster is period-specific.'}})
    except HTTPException: raise
    except Exception as e: raise HTTPException(400,f'Women CSP roster upload failed: {e}')

@router.get('/women-csp-incentive/reconciliation')
def women_csp_incentive_reconciliation():
    """Reconcile current Women CSP roster and bank-paid Rule 24 rows against the active BC report."""
    if not WOMEN_COUNTS.exists():
        return {'available':False,'status':'WOMEN_ROSTER_MISSING','message':'Upload the current-period Women CSP roster.','rows':[]}
    if not (CM/'latest_commission.csv').exists():
        return {'available':False,'status':'BC_REPORT_MISSING','message':'Upload the matching-period BC Commission Report.','rows':[],'slab_rates':DFS_RATES,'rule_matrix':DFS_RULE_MATRIX}
    try:
        roster=pd.read_csv(WOMEN_COUNTS,dtype={'csp_id':str},low_memory=False)
        bc=pd.read_csv(CM/'latest_commission.csv',dtype={'csp_id':str},low_memory=False)
        meta=json.loads(WOMEN_META.read_text()) if WOMEN_META.exists() else {}
        period=meta.get('period')
        # Require the uploaded BC report to cover the same selected period when metadata is available.
        source_meta=load_metadata().get('commission') or {}
        tx_meta=load_metadata().get('transactions') or {}
        bc_start=source_meta.get('period_start'); bc_end=source_meta.get('period_end')
        tx_start=tx_meta.get('period_start'); tx_end=tx_meta.get('period_end')
        if period and bc_start and bc_end and not (str(bc_start)[:7] <= period <= str(bc_end)[:7]):
            return {'available':False,'status':'PERIOD_MISMATCH','message':f'Women CSP roster period {period} does not match BC report period {bc_start} to {bc_end}.','rows':[]}
        if period and tx_start and tx_end:
            if str(tx_start)[:7] != str(tx_end)[:7]:
                return {'available':False,'status':'MULTI_PERIOD_REQUIRES_MONTHLY_TRANSACTION_SOURCE','message':f'Women CSP incentive is monthly, but successful transactions span {tx_start} to {tx_end}. Upload/filter the successful-transaction source to {period} before running Rule 24.','rows':[]}
            if str(tx_start)[:7] != period:
                return {'available':False,'status':'PERIOD_MISMATCH','message':f'Women CSP roster period {period} does not match successful transaction period {tx_start[:7]}.','rows':[]}
        from app.services.women_csp_incentive import reconcile_women_csp_incentive
        from app.api.reconciliation import load_result
        # Alias map intentionally empty: do not reuse a prior-month identity correction.
        aliases={}
        try:
            expected_transactions=load_result()
        except Exception as exc:
            return {'available':False,'status':'EXPECTED_TRANSACTION_COMMISSION_MISSING','message':f'Run the main successful-transaction reconciliation with the approved rate master first: {exc}','rows':[]}
        result=reconcile_women_csp_incentive(roster,bc,period=period,id_aliases=aliases,expected_transactions=expected_transactions)
        result['source']={'women_roster':meta.get('filename'),'bc_report':source_meta.get('filename'),'period':period,'expected_base':'eligible core transaction-based commission rows from CSP-wise BC commission report; successful-transaction/rate reconciliation is an independent cross-check'}
        return _response(result)
    except Exception as e:
        return {'available':False,'status':'RECONCILIATION_ERROR','message':f'Women CSP incentive reconciliation failed: {e}','rows':[]}

@router.post('/dfs-incentive')
async def dfs_incentive(file:UploadFile=File(...),sheet_name:Optional[str]=Form(None)):
    """Upload monthly CSP-wise DFS slab evidence. Slab amounts are persistent rules; monthly CSP assignments are uploaded each period."""
    try:
        content,sha=await _read(file,sheet_name,'dfs_incentive')
        period=_month_from_text(file.filename)
        if file.filename.lower().endswith('.xlsx'):
            xl=excel_io.excel_file(content)
            names=[sheet_name] if sheet_name in xl.sheet_names else xl.sheet_names
            raw=None; chosen=None
            for nm in names:
                candidate=excel_io.read_excel(content,sheet_name=nm,header=None,engine='openpyxl')
                # DFS source exports can have a two-row header: MTD Achievement/slab
                # is on row 1 while CSP profile headers are on row 2.
                for ridx in range(min(12,len(candidate))):
                    vals=[re.sub(r'[^a-z0-9]+',' ',str(x).lower()).strip() for x in candidate.iloc[ridx].tolist()]
                    if any('csp name' in x for x in vals) and (any('login day' in x for x in vals) or any('csp code' in x or 'csp id' in x for x in vals)):
                        headers=[]
                        for ci in range(candidate.shape[1]):
                            top=str(candidate.iloc[ridx-1,ci]).strip() if ridx>0 and pd.notna(candidate.iloc[ridx-1,ci]) else ''
                            cur=str(candidate.iloc[ridx,ci]).strip() if pd.notna(candidate.iloc[ridx,ci]) else ''
                            headers.append(cur or top or f'blank_{ci}')
                        candidate.columns=headers
                        raw=candidate.iloc[ridx+1:].copy(); chosen=nm; break
                if raw is not None: break
            if raw is None: raise HTTPException(400,'DFS sheet header row not found. Required columns: CSP Code/ID and Slab/MTD Achievement.')
        else:
            raw=pd.read_csv(BytesIO(content),low_memory=False); chosen=None
        raw=_clean_supplement_columns(raw)
        df,mapped=_alias_columns(raw,{'csp_id':['csp_id','csp_code','csp_code_new','csp','csp_id_code'], 'csp_name':['csp_name','name'], 'slab':['slab','assigned_slab','dfs_assigned_slab','assigned_dfs_slab','mtd_achievement','achievement','dfs_slab'], 'period':['period','month','month_year','report_month']})
        # Legacy DFS export may mislabel column B as 'Total Login Day (<month>)'
        # even though one row contains a CSP ID and remaining rows contain login-day counts.
        # Preserve that column as a candidate ID field; invalid/non-ID values are blanked
        # below and can only resolve through a globally unique CSP name in the full BC report.
        if 'csp_id' not in df.columns:
            legacy_identity_col = next((c for c in raw.columns if 'total login day' in re.sub(r'[^a-z0-9]+',' ',str(c).lower()).strip()), None)
            if legacy_identity_col is not None:
                df['csp_id'] = raw[legacy_identity_col].values
                mapped['csp_id'] = str(legacy_identity_col)
        if 'csp_id' not in df.columns and 'csp_name' not in df.columns:
            raise HTTPException(400,'DFS source must contain official CSP Code/CSP ID or CSP Name for controlled name-based resolution.')
        if 'csp_id' not in df.columns:
            df['csp_id'] = ''
        if 'csp_name' not in df.columns:
            raise HTTPException(400,'DFS source is missing CSP Name; name-only rows cannot be resolved safely.')
        if 'slab' not in df.columns:
            # Legacy MTD Achievement header often includes a month suffix, e.g. "MTD Achievement August'26".
            slab_source_col = next((c for c in raw.columns if 'mtd achievement' in re.sub(r'[^a-z0-9]+',' ',str(c).lower()).strip()), None)
            if slab_source_col is None:
                valid_slab_tokens = {'SLAB-1','SLAB-2','SLAB-3','SLAB-4','SUPER SLAB','SUPERSLAB','SUPER-SLAB'}
                for c in raw.columns:
                    values = raw[c].astype(str).str.strip().str.upper().str.replace(r'\s+',' ',regex=True)
                    if values.isin(valid_slab_tokens).any():
                        slab_source_col = c; break
            if slab_source_col is not None:
                df['slab'] = raw[slab_source_col].values
                mapped['slab'] = str(slab_source_col)
            else:
                raise HTTPException(400,'DFS source is missing the assigned slab column (Slab-1, Slab-2, Slab-3, Slab-4 or Super Slab).')
        df['csp_id']=_clean_csp_ids(df['csp_id'])
        df['slab']=df['slab'].astype('string').str.strip().str.upper().str.replace(r'\s+',' ',regex=True)
        df['slab']=df['slab'].replace({'SUPERSLAB':'SUPER SLAB','SUPER-SLAB':'SUPER SLAB'})
        if 'csp_name' not in df.columns: df['csp_name']=''
        df['csp_name']=df['csp_name'].fillna('').astype(str).str.strip()
        if 'period' in df.columns:
            df['period']=df['period'].map(lambda x: (str(x).strip() if re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',str(x).strip()) else _month_from_text(x)))
        else:
            period = period or next((_month_from_text(c) for c in raw.columns if _month_from_text(c)), None)
            df['period']=period
        # Keep every populated slab assignment that has at least one identity field.
        # A blank CSP name must not silently discard a valid official CSP ID.
        # Rows with neither ID nor name are blank/footer rows and are excluded.
        identity_present = df['csp_id'].astype(str).str.strip().ne('') | df['csp_name'].astype(str).str.strip().ne('')
        df=df[df['slab'].notna() & df['slab'].ne('') & identity_present].copy()
        # A source row whose legacy 'Total Login Day' field contains a number rather than a CSP ID is retained as unresolved; it must not be falsely matched as a CSP.
        df.loc[~df['csp_id'].str.match(r'^1A85\d{4}$',na=False),'csp_id']=''
        invalid=~df['slab'].isin(DFS_RATES) | df['period'].isna()
        if invalid.any():
            examples=df.loc[invalid,['csp_id','slab','period']].head(8).to_dict('records')
            raise HTTPException(400,f'DFS source has invalid CSP/slab/period rows: {examples}. Confirm CSP IDs, slab labels and month/year.')
        if df.loc[df['csp_id'].ne(''),'csp_id'].duplicated().any():
            dups=df.loc[df['csp_id'].ne('') & df['csp_id'].duplicated(keep=False),'csp_id'].unique().tolist()[:10]
            raise HTTPException(400,f'DFS source contains duplicate CSP IDs; resolve duplicate slab assignments before upload: {dups}')
        df['expected_incentive']=df['slab'].map(DFS_RATES)
        df['transaction_type']='DFS PRIORITIES INCENTIVE'
        df['source_file']=file.filename
        out=df[['csp_id','csp_name','slab','expected_incentive','transaction_type','period','source_file']].copy()
        out.to_csv(DFS_COUNTS,index=False)
        periods=sorted(out['period'].unique().tolist())
        meta={'filename':file.filename,'sha256':sha,'sheet_name':chosen,'periods':periods,'rows':len(out),'mapped_columns':mapped,'rates':DFS_RATES,'parser_version':'dfs-incentive-v3-global-identity-safety-2026-10'}
        DFS_META.write_text(json.dumps(meta,indent=2),encoding='utf-8')
        clear_cache()
        return _response({'file_type':'dfs_incentive','filename':file.filename,'sheet_name':chosen,'saved':True,'validation':{'valid':True,'rows':len(out),'periods':periods,'mapped_columns':mapped,'slab_rates':DFS_RATES,'expected_total':round(float(out['expected_incentive'].sum()),2),'source_rows_without_official_csp_id':int(out['csp_id'].astype(str).str.strip().eq('').sum()),'identity_warning':'Rows without official CSP IDs require a separate approved CSP ID mapping; name fallback is allowed only when the name is globally unique in the full BC report.','parser_version':'dfs-incentive-v3-global-identity-safety-2026-10','rule_matrix':DFS_RULE_MATRIX,'note':'Monthly extra incentive rates are applied deterministically. Slab-4 is ₹2,200. Scheme targets and average-balance multipliers are preserved in the permanent rule matrix; slab eligibility is not inferred without current-period scheme counts.'}})
    except HTTPException: raise
    except Exception as e: raise HTTPException(400,f'DFS incentive upload failed: {e}')

@router.get('/dfs-incentive/rules')
def dfs_incentive_rules():
    """Return the permanent DFS target, monthly incentive and average-balance matrix."""
    return {'available': True, 'rule_matrix': DFS_RULE_MATRIX, 'slab_rates': DFS_RATES,
            'rule_version': 'dfs-monthly-target-matrix-2026-10-15', 'reconciliation_engine_version': '62.6.108-windows-path-install-fix'}


@router.get('/dfs-incentive/reconciliation')
def dfs_incentive_reconciliation():
    """Compare current uploaded DFS monthly slab assignments against current BC DFS commission rows by exact CSP ID."""
    if not DFS_COUNTS.exists(): return {'available':False,'status':'SOURCE_MISSING','message':'Upload the current-month DFS CSP/slab sheet.','rows':[],'slab_rates':DFS_RATES,'rule_matrix':DFS_RULE_MATRIX}
    src=pd.read_csv(DFS_COUNTS,dtype={'csp_id':str},low_memory=False)
    if not (CM/'latest_commission.csv').exists(): return {'available':False,'status':'BC_REPORT_MISSING','message':'Upload the matching-period BC Commission Report.','rows':[],'slab_rates':DFS_RATES,'rule_matrix':DFS_RULE_MATRIX}
    bc=pd.read_csv(CM/'latest_commission.csv',dtype={'csp_id':str},low_memory=False)
    # The normalized BC commission schema uses `actual_commission`, not `commission`.
    # Accept the legacy alias too, but never silently sum an absent column as zero.
    amount_col = 'actual_commission' if 'actual_commission' in bc.columns else ('commission' if 'commission' in bc.columns else None)
    for col in ['csp_id','transaction_type']:
        if col not in bc.columns: return {'available':False,'status':'BC_SCHEMA_INVALID','message':f'BC commission data is missing {col}.','rows':[]}
    if amount_col is None: return {'available':False,'status':'BC_SCHEMA_INVALID','message':'BC commission data is missing actual_commission.','rows':[]}
    bc['csp_id']=_clean_csp_ids(bc['csp_id']); bc['type_norm']=bc['transaction_type'].astype(str).str.upper().str.strip()
    # Preserve the complete BC CSP identity population before filtering to DFS payment rows.
    # A CSP who was not paid DFS still appears under other transaction types; using only
    # DFS-paid rows for name resolution incorrectly labels such CSPs as identity-unresolved.
    bc_all = bc[['csp_id', 'csp_name']].copy() if 'csp_name' in bc.columns else bc[['csp_id']].copy()
    bc=bc[bc['type_norm'].eq('DFS PRIORITIES INCENTIVE')].copy()
    bc[amount_col]=pd.to_numeric(bc[amount_col],errors='coerce')
    invalid_amounts=int(bc[amount_col].isna().sum())
    if invalid_amounts:
        return {'available':False,'status':'BC_AMOUNT_INVALID','message':f'{invalid_amounts} DFS BC commission row(s) have missing or invalid commission amounts. Resolve them before reconciliation.','rows':[]}
    if 'csp_name' in bc.columns:
        bc=bc.groupby('csp_id',as_index=False).agg(actual_commission=(amount_col,'sum'),csp_name=('csp_name','first'))
    else:
        bc=bc.groupby('csp_id',as_index=False)[amount_col].sum().rename(columns={amount_col:'actual_commission'})
    periods=sorted(src['period'].dropna().astype(str).unique().tolist())
    source_periods=periods
    # DFS is a monthly CSP incentive and must be period-checked against the
    # active BC commission report, not the raw transaction ledger. A transaction
    # file can legitimately contain multiple months (e.g. a full-year export),
    # which must not block a single-month DFS-to-BC reconciliation.
    metadata=load_metadata()
    commission_meta=metadata.get('commission') or {}
    commission_periods=[]
    cs, ce = commission_meta.get('period_start'), commission_meta.get('period_end')
    if cs and ce:
        cstart=pd.to_datetime(cs,errors='coerce')
        cend=pd.to_datetime(ce,errors='coerce')
        if pd.notna(cstart) and pd.notna(cend):
            commission_periods=sorted(pd.date_range(cstart.to_period('M').start_time, cend.to_period('M').start_time, freq='MS').strftime('%Y-%m').unique().tolist())
    if not commission_periods:
        inferred=_month_from_text(commission_meta.get('filename',''))
        if inferred:
            commission_periods=[inferred]
    if not commission_periods:
        return {'available':False,'status':'BC_PERIOD_UNKNOWN','message':'The active BC Commission Report period could not be verified from its metadata or filename. Re-upload the report with a month/year in the filename or provide a period column before DFS reconciliation.','rows':[]}
    if len(source_periods)!=1 or source_periods!=commission_periods:
        return {'available':False,'status':'PERIOD_MISMATCH','message':f"DFS source period {source_periods} does not match active BC commission report period {commission_periods}. Upload the matching month's BC report.",'rows':[]}
    identified=src[src['csp_id'].astype(str).str.match(r'^1A85\d{4}$',na=False)].copy()
    unresolved=src[~src.index.isin(identified.index)].copy()
    # Legacy DFS exports may put login-day counts in the CSP-code column.
    # Fallback only to unique exact CSP-name matches; ambiguous names stay unresolved.
    def _norm_name(value):
        return re.sub(r'[^a-z0-9]+',' ',str(value or '').lower()).strip()
    if 'csp_name' in bc_all.columns:
        bc_all['name_norm']=bc_all['csp_name'].map(_norm_name)
    else:
        bc_all['name_norm']=''
    if not unresolved.empty and 'csp_name' in unresolved.columns:
        unresolved=unresolved.copy()
        unresolved['matched_name_norm']=unresolved['csp_name'].map(_norm_name)
        # A name is safe only if it maps to exactly one official CSP ID across the
        # entire BC report, not merely within the subset that received DFS incentive.
        # Common names shared by different CSP IDs must remain unresolved.
        bc_name_counts=bc_all.loc[bc_all['name_norm'].ne('')].groupby('name_norm')['csp_id'].nunique()
        unique_names=set(bc_name_counts[bc_name_counts.eq(1)].index)
        name_to_id=(bc_all.loc[bc_all['name_norm'].isin(unique_names),['name_norm','csp_id']]
                    .drop_duplicates('name_norm').set_index('name_norm')['csp_id'].to_dict())
        unresolved['csp_id']=unresolved.apply(
            lambda r: name_to_id.get(r['matched_name_norm'],'')
            if r['matched_name_norm'] in unique_names else '', axis=1)
        name_resolved=unresolved[unresolved['csp_id'].astype(str).str.match(r'^1A85\d{4}$',na=False)].copy()
        # Never let a name-based fallback create duplicate source assignments for
        # a CSP already present by official ID, or map multiple source rows to the
        # same ID. Those records remain explicit unresolved exceptions.
        existing_ids=set(identified['csp_id'].astype(str))
        candidate_ids=name_resolved['csp_id'].astype(str)
        candidate_counts=candidate_ids.value_counts()
        conflicting_ids=set(candidate_counts[candidate_counts.gt(1)].index) | (set(candidate_ids) & existing_ids)
        if conflicting_ids:
            conflict_mask=name_resolved['csp_id'].astype(str).isin(conflicting_ids)
            unresolved_conflicts=name_resolved.loc[conflict_mask].copy()
            unresolved_conflicts['csp_id']=''
            unresolved=pd.concat([unresolved, unresolved_conflicts], axis=0)
            name_resolved=name_resolved.loc[~conflict_mask].copy()
        unresolved=unresolved[~unresolved.index.isin(name_resolved.index)].copy()
        identified=pd.concat([identified,name_resolved.drop(columns=['matched_name_norm'],errors='ignore')],ignore_index=True)
    bc=bc.drop(columns=['name_norm'],errors='ignore')
    merged=identified.merge(bc,on='csp_id',how='outer',indicator=True,suffixes=('','_bc'))
    # Both sources carry a CSP name: show the DFS sheet's name, else the BC report's (V62.6.211).
    if 'csp_name_bc' in merged.columns:
        source_name=merged['csp_name'].astype('string').str.strip() if 'csp_name' in merged.columns else pd.Series(pd.NA,index=merged.index,dtype='string')
        merged['bc_csp_name']=merged['csp_name_bc']
        merged['csp_name']=source_name.where(source_name.notna() & source_name.ne(''),merged['csp_name_bc'])
    merged['expected_incentive']=pd.to_numeric(merged.get('expected_incentive'),errors='coerce')
    merged['actual_commission']=pd.to_numeric(merged.get('actual_commission'),errors='coerce')
    merged['variance_actual_minus_expected']=merged['actual_commission']-merged['expected_incentive']
    def status(r):
        if r['_merge']=='left_only': return 'MISSING_IN_BC'
        if r['_merge']=='right_only': return 'BC_ONLY_CSP'
        if pd.isna(r['actual_commission']): return 'ACTUAL_AMOUNT_MISSING'
        if abs(float(r['variance_actual_minus_expected'] or 0))<0.01: return 'MATCHED'
        return 'AMOUNT_MISMATCH'
    merged['status']=merged.apply(status,axis=1)
    if not unresolved.empty:
        unresolved=unresolved.copy(); unresolved['actual_commission']=pd.NA; unresolved['variance_actual_minus_expected']=pd.NA; unresolved['status']='UNRESOLVED_CSP_ID'; unresolved['_merge']='left_only'
        # All-NA placeholder columns on unresolved rows are omitted before concat;
        # this preserves the merged schema while avoiding dtype inference warnings.
        unresolved_nonempty=[c for c in unresolved.columns if not unresolved[c].isna().all()]
        merged=pd.concat([merged,unresolved[unresolved_nonempty]],ignore_index=True,sort=False)
    rows=[]
    for _,r in merged.iterrows():
        name=r.get('csp_name'); bc_name=r.get('bc_csp_name')
        rows.append({'csp_id':r.get('csp_id'),'csp_name':None if pd.isna(name) else str(name),'bc_csp_name':None if pd.isna(bc_name) else str(bc_name),'slab':r.get('slab'),'expected_incentive':None if pd.isna(r.get('expected_incentive')) else float(r.get('expected_incentive')),'actual_commission':None if pd.isna(r.get('actual_commission')) else float(r.get('actual_commission')),'variance_actual_minus_expected':None if pd.isna(r.get('variance_actual_minus_expected')) else float(r.get('variance_actual_minus_expected')),'status':r['status']})
    matched=sum(r['status']=='MATCHED' for r in rows); expected=sum(r['expected_incentive'] or 0 for r in rows if r['expected_incentive'] is not None); actual=sum(r['actual_commission'] or 0 for r in rows if r['actual_commission'] is not None)
    return {'available':True,'status':'READY','periods':source_periods,'summary':{
        'source_rows':int(len(src)),
        'source_csp_count':int(identified['csp_id'].astype(str).str.match(r'^1A85\d{4}$',na=False).sum()),
        'unresolved_source_rows':int(len(unresolved)),
        'bc_csp_count':int(bc['csp_id'].astype(str).str.match(r'^1A85\d{4}$',na=False).sum()),
        'identity_resolution_policy':'official CSP ID first; otherwise exact name only when globally unique across all CSP IDs in the full BC report',
        'matched':matched,'exceptions':len(rows)-matched,
        'expected_total':round(expected,2),'actual_total':round(actual,2),
        'variance_actual_minus_expected':round(actual-expected,2)
    },'rows':rows,'slab_rates':DFS_RATES,'rule_matrix':DFS_RULE_MATRIX,'matching_policy':'Official CSP ID first; fallback only to an exact name globally unique across the full BC report. Ambiguous or conflicting names remain unresolved.'}

# Permanent SBI TAB financial-transaction incentive rule.
MATM_COUNTS=SUPPLEMENTAL/'latest_matm_incentive_counts.csv'
MATM_META=SUPPLEMENTAL/'latest_matm_incentive_metadata.json'
MATM_RATE=3.0
MATM_CAP=1000.0
MATM_TYPE='MATM CASH TRANSACTIONS INCENTIVE'
TAB_COUNTS=SUPPLEMENTAL/'latest_tab_incentive_counts.csv'
TAB_META=SUPPLEMENTAL/'latest_tab_incentive_metadata.json'
TAB_RATE=5.0
TAB_CAP=1000.0
TAB_TYPE='TAB TRANSACTIONS INCENTIVE'


def _drop_blank_matm_source_rows(raw: pd.DataFrame, id_col: str, name_col: Optional[str], count_cols: list) -> pd.DataFrame:
    """Ignore truly empty/formatted rows, including text placeholders like 'nan'.

    Only CSP identity and the selected count columns determine whether a row is a
    meaningful source record. A populated count with a missing CSP identity (or vice
    versa) is retained so validation reports it instead of silently discarding it.
    """
    relevant = [id_col] + ([name_col] if name_col else []) + [col for col, _ in count_cols]
    null_tokens = {'', 'nan', 'none', 'null', '<na>', 'nat', 'n/a'}
    present = pd.Series(False, index=raw.index)
    for col in relevant:
        values = raw[col]
        text_values = values.map(lambda v: '' if pd.isna(v) else str(v).strip().casefold())
        present |= ~text_values.isin(null_tokens)
    return raw.loc[present].copy()


@router.post('/matm-incentive')
@router.post('/matm-incentive-v2')
async def matm_incentive(file: UploadFile = File(...), sheet_name: Optional[str] = Form(None)):
    """Upload current-period CSP-wise m-ATM cash transaction counts. SBI CM060: ₹3/count, ₹1,000/CSP/month cap."""
    try:
        content, sha = await _read(file, sheet_name, 'matm_incentive')
        frames=[]; chosen_names=[]; mapped_all={}
        if file.filename.lower().endswith('.xlsx'):
            xl=excel_io.excel_file(content)
            names=[sheet_name] if sheet_name in xl.sheet_names else xl.sheet_names
            for nm in names:
                raw0=excel_io.read_excel(content,sheet_name=nm,engine='openpyxl')
                # Support title rows in original SBI exports: scan for the real CSP/count header.
                raw0=_clean_supplement_columns(raw0)
                def _is_matm_header(frame):
                    cols=list(frame.columns)
                    has_id=any(c in ('csp_id','csp_code','csp_code_new','csp','csp_id_code','csp_code_id','csp_id_no','csp_code_no') or c.startswith('csp_code_') for c in cols)
                    def is_monthly_matm_count(c):
                        has_period = _month_from_text(c) is not None
                        has_matm_context = any(token in c for token in ('matm','m_atm','m_atm_cash','atm','financial_transaction','financial_txn'))
                        has_count_semantics = any(token in c for token in ('count','transaction','txn','financial','number_of'))
                        return has_period and has_matm_context and has_count_semantics
                    generic_counts = ('matm_transaction_count','matm_count','matm_transactions','matm_transaction','transaction_count','eligible_transactions','count','financial_transaction_count','financial_transactions','txn_count','no_of_transactions','number_of_transactions')
                    has_generic_count = any(c in generic_counts for c in cols)
                    # Original CSP-wise reports often have a generic "mATM Transaction"
                    # count column and put the period only in the filename/sheet name.
                    # Accept that layout only when an explicit month/year is available.
                    explicit_period = _month_from_text(file.filename) or _month_from_text(nm)
                    has_count=any(is_monthly_matm_count(c) for c in cols) or (any(c in ('period','month','month_year','report_month') for c in cols) and has_generic_count) or (explicit_period and has_generic_count and any(('matm' in c or 'm_atm' in c or 'atm' in c) and any(t in c for t in ('transaction','txn','count')) for c in cols))
                    return has_id and has_count
                if not _is_matm_header(raw0):
                    found_header=False
                    for hdr in range(0, 20):
                        try:
                            test=_clean_supplement_columns(excel_io.read_excel(content,sheet_name=nm,header=hdr,engine='openpyxl'))
                        except Exception:
                            continue
                        if _is_matm_header(test):
                            raw0=test; found_header=True; break
                    if not found_header:
                        continue
                # Source reports may use a month in the count-column heading (e.g. "mATM Transaction Count August 2026").
                id_col=next((c for c in raw0.columns if c in ('csp_id','csp_code','csp_code_new','csp','csp_id_code','csp_code_id','csp_id_no','csp_code_no')),None)
                name_col=next((c for c in raw0.columns if c in ('csp_name','name')),None)
                count_cols=[(c,_month_from_text(c)) for c in raw0.columns if _month_from_text(c) and any(t in c for t in ('matm','m_atm','atm','financial_transaction','financial_txn')) and any(t in c for t in ('count','transaction','txn','financial'))]
                period_col=next((c for c in raw0.columns if c in ('period','month','month_year','report_month')),None)
                generic_count=next((c for c in raw0.columns if c in ('matm_transaction_count','matm_count','matm_transactions','matm_transaction','transaction_count','eligible_transactions','count','financial_transaction_count','financial_transactions','txn_count','no_of_transactions','number_of_transactions')),None)
                filename_period = _month_from_text(file.filename) or _month_from_text(nm)
                generic_matm_label = bool(generic_count and any(('matm' in c or 'm_atm' in c or 'atm' in c) and any(t in c for t in ('transaction','txn','count')) for c in raw0.columns))
                if id_col and (count_cols or (period_col and generic_count) or (filename_period and generic_count and generic_matm_label)):
                    raw=raw0; chosen_names=[nm]; mapped_all={'csp_id':id_col,'csp_name':name_col,'count_columns':[c for c,_ in count_cols] or ([generic_count] if generic_count else []),'period_from_filename':filename_period}; break
            else:
                raise HTTPException(400,'m-ATM source requires CSP Code/ID and a month-labelled mATM transaction-count column, or Period + transaction count.')
        else:
            raw=_clean_supplement_columns(pd.read_csv(BytesIO(content),low_memory=False))
            id_col=next((c for c in raw.columns if c in ('csp_id','csp_code','csp_code_new','csp','csp_id_code','csp_code_id','csp_id_no','csp_code_no')),None)
            name_col=next((c for c in raw.columns if c in ('csp_name','name')),None)
            count_cols=[(c,_month_from_text(c)) for c in raw.columns if _month_from_text(c) and any(t in c for t in ('matm','m_atm','atm','financial_transaction','financial_txn')) and any(t in c for t in ('count','transaction','txn','financial'))]
            period_col=next((c for c in raw.columns if c in ('period','month','month_year','report_month')),None)
            generic_count=next((c for c in raw.columns if c in ('matm_transaction_count','matm_count','matm_transactions','matm_transaction','transaction_count','eligible_transactions','count','financial_transaction_count','financial_transactions','txn_count','no_of_transactions','number_of_transactions')),None)
            filename_period = _month_from_text(file.filename) or _active_single_month_period()
            generic_matm_label = bool(generic_count and any(('matm' in c or 'm_atm' in c or 'atm' in c) and any(t in c for t in ('transaction','txn','count')) for c in raw.columns))
            if not id_col or not (count_cols or (period_col and generic_count) or (filename_period and generic_count and generic_matm_label)):
                raise HTTPException(400,'m-ATM source requires CSP Code/ID and a month-labelled m-ATM transaction-count column, or an explicit month/year in the filename plus a clearly labelled m-ATM count column.')
            chosen_names=['CSV']; mapped_all={'csp_id':id_col,'csp_name':name_col,'count_columns':[c for c,_ in count_cols]}
        id_col=next((c for c in raw.columns if c in ('csp_id','csp_code','csp_code_new','csp','csp_id_code','csp_code_id','csp_id_no','csp_code_no')),None)
        name_col=next((c for c in raw.columns if c in ('csp_name','name')),None)
        count_cols=[(c,_month_from_text(c)) for c in raw.columns if _month_from_text(c) and any(t in c for t in ('matm','m_atm','atm','financial_transaction','financial_txn')) and any(t in c for t in ('count','transaction','txn','financial'))]
        period_col=next((c for c in raw.columns if c in ('period','month','month_year','report_month')),None)
        generic_count=next((c for c in raw.columns if c in ('matm_transaction_count','matm_count','matm_transactions','matm_transaction','transaction_count','eligible_transactions','count','financial_transaction_count','financial_transactions','txn_count','no_of_transactions','number_of_transactions')),None)
        if not id_col: raise HTTPException(400,'m-ATM source is missing CSP Code/ID.')
        # Ignore trailing/formatting rows where CSP identity, name and count are all blank.
        # Keep partially populated rows so the validation below flags them explicitly.
        raw=_drop_blank_matm_source_rows(raw,id_col,name_col,count_cols)
        records=[]
        if count_cols:
            for col,period in count_cols:
                for _,row in raw.iterrows():
                    records.append({'period':period,'csp_id':row.get(id_col),'csp_name':row.get(name_col,'') if name_col else '', 'matm_transaction_count':row.get(col)})
        else:
            filename_period = _month_from_text(file.filename) or _month_from_text(chosen_names[0] if chosen_names else '') or _active_single_month_period()
            for _,row in raw.iterrows():
                period=_month_from_text(row.get(period_col)) if period_col else filename_period
                records.append({'period':period,'csp_id':row.get(id_col),'csp_name':row.get(name_col,'') if name_col else '', 'matm_transaction_count':row.get(generic_count)})
        out=pd.DataFrame(records)
        # Exclude explicit summary/footer labels only when they carry no count value.
        # A populated TOTAL row is retained for validation unless the total is proven
        # to equal the valid CSP-detail sum later in the pipeline.
        if not out.empty:
            summary_label = out['csp_id'].astype(str).str.strip().str.upper().isin({'TOTAL','GRAND TOTAL','SUBTOTAL','OVERALL TOTAL'})
            summary_without_count = summary_label & pd.to_numeric(out['matm_transaction_count'], errors='coerce').isna()
            out = out.loc[~summary_without_count].copy()
        # Second-stage guard at the normalized-record boundary. Some Excel readers
        # or client-generated exports preserve formatted trailing rows despite the
        # raw-frame filter; discard only records where ID, name AND count are empty.
        # Partially populated rows are deliberately retained and rejected below.
        def _is_blank_cell(value):
            if value is None or pd.isna(value):
                return True
            return str(value).strip().casefold() in {'', 'nan', 'none', 'null', '<na>', 'nat', 'n/a'}
        if not out.empty:
            blank_record = out.apply(
                lambda row: _is_blank_cell(row.get('csp_id'))
                and _is_blank_cell(row.get('csp_name'))
                and _is_blank_cell(row.get('matm_transaction_count')),
                axis=1,
            )
            out = out.loc[~blank_record].copy()
        if out.empty:
            raise HTTPException(400, 'm-ATM source contains no populated CSP/count rows after blank-row cleanup.')
        out['period']=out['period'].astype(str).str.strip()
        out['csp_id']=_clean_csp_ids(out['csp_id'])
        out['csp_name']=out['csp_name'].fillna('').astype(str).str.strip()
        out['matm_transaction_count']=pd.to_numeric(out['matm_transaction_count'],errors='coerce')
        # Final normalized-boundary cleanup. This intentionally happens after ID
        # normalization and numeric coercion so null-like IDs and NaN counts cannot
        # leak into validation from Excel's formatted trailing rows.
        null_tokens={'','nan','none','null','<na>','nat','n/a'}
        blank_id=out['csp_id'].map(lambda v: str(v).strip().casefold() in null_tokens)
        blank_name=out['csp_name'].map(lambda v: str(v).strip().casefold() in null_tokens)
        blank_count=out['matm_transaction_count'].isna()
        out=out.loc[~(blank_id & blank_name & blank_count)].copy()
        if out.empty:
            raise HTTPException(400,'m-ATM source contains no populated CSP/count rows after normalized blank-row cleanup (parser matm-incentive-v2).')
        invalid=(~out['period'].str.match(r'^20\d{2}-(0[1-9]|1[0-2])$')) | out['csp_id'].eq('') | out['csp_id'].str.casefold().isin(null_tokens) | out['matm_transaction_count'].isna() | (out['matm_transaction_count']<0) | (out['matm_transaction_count']%1!=0)
        if invalid.any():
            raise HTTPException(400,f'Invalid m-ATM source rows (parser matm-incentive-v2; period, nonblank CSP identity, non-negative whole count required): {out.loc[invalid].head(8).to_dict("records")}')
        out['identity_status']=out['csp_id'].str.match(r'^1A85\d{4}$',na=False).map({True:'OFFICIAL CSP ID',False:'UNRESOLVED ID - exact match only'})
        if out.duplicated(['period','csp_id']).any():
            dups=out.loc[out.duplicated(['period','csp_id'],keep=False),['period','csp_id']].to_dict('records')
            raise HTTPException(400,f'Duplicate CSP/month m-ATM rows; resolve before upload: {dups[:10]}')
        out['expected_incentive']=(out['matm_transaction_count']*MATM_RATE).clip(upper=MATM_CAP)
        out['transaction_type']=MATM_TYPE; out['source_file']=file.filename
        out=out[['period','csp_id','csp_name','identity_status','matm_transaction_count','expected_incentive','transaction_type','source_file']]
        out.to_csv(MATM_COUNTS,index=False)
        periods=sorted(out.period.unique().tolist())
        MATM_META.write_text(json.dumps({'filename':file.filename,'sha256':sha,'sheet_name':','.join(chosen_names),'periods':periods,'rows':len(out),'mapped_columns':mapped_all,'rate_per_transaction':MATM_RATE,'monthly_cap':MATM_CAP,'rule_id':'SBI-CM060','parser_version':'matm-incentive-v2-normalized-blank-row-boundary'},indent=2),encoding='utf-8')
        save_source('matm_incentive',file.filename,','.join(chosen_names),len(out),min(periods)+'-01',max(periods)+'-01',extra={'periods':periods,'rule_id':'SBI-CM060'},sha256=sha)
        clear_cache()
        return _response({'file_type':'matm_incentive','filename':file.filename,'sheet_name':','.join(chosen_names),'saved':True,'validation':{'valid':True,'rows':len(out),'periods':periods,'mapped_columns':mapped_all,'rate_per_transaction':MATM_RATE,'monthly_cap':MATM_CAP,'expected_total':round(float(out.expected_incentive.sum()),2),'source_transaction_count':int(out.matm_transaction_count.sum()),'csp_month_controls':len(out),'unresolved_identity_rows':int(out['identity_status'].ne('OFFICIAL CSP ID').sum()),'unresolved_identity_examples':out.loc[out['identity_status'].ne('OFFICIAL CSP ID'),['csp_id','csp_name','matm_transaction_count']].head(10).to_dict('records'),'rule_id':'SBI-CM060','note':'Expected commission is independently calculated from uploaded CSP-wise m-ATM counts; BC Report is used only for actual payment. Rows without an official CSP ID remain explicitly unresolved and should be corrected before final settlement sign-off.'}})
    except HTTPException: raise
    except Exception as e: raise HTTPException(400,f'm-ATM incentive upload failed: {e}')


@router.get('/matm-incentive/reconciliation')
@memo_on_files(lambda:[MATM_COUNTS,MATM_META,CM/'latest_commission.csv',TX/'latest_transactions.csv'])
def matm_incentive_reconciliation():
    """Compare independently uploaded CSP/month counts to BC-paid m-ATM incentive, using exact CSP IDs."""
    if not MATM_COUNTS.exists():
        return {'available':False,'status':'SOURCE_MISSING','message':'Upload current-period CSP-wise m-ATM transaction counts.','rows':[]}
    if not (CM/'latest_commission.csv').exists():
        return {'available':False,'status':'BC_REPORT_MISSING','message':'Upload the matching-period BC Commission Report.','rows':[]}
    src=pd.read_csv(MATM_COUNTS,dtype={'csp_id':str},low_memory=False)
    bc=pd.read_csv(CM/'latest_commission.csv',dtype={'csp_id':str},low_memory=False)
    amount='actual_commission' if 'actual_commission' in bc.columns else ('commission' if 'commission' in bc.columns else None)
    if not amount or not {'csp_id','transaction_type'}.issubset(bc.columns):
        return {'available':False,'status':'BC_SCHEMA_INVALID','message':'BC commission data requires CSP ID, transaction type, and actual commission.','rows':[]}
    # One BC commission report is a single-period settlement. Do not aggregate
    # multiple source months against that single actual-side report.
    source_periods=set(src['period'].dropna().astype(str).str.strip().unique()) if 'period' in src.columns else set()
    if len(source_periods) != 1:
        return {'available':False,'status':'SOURCE_PERIOD_AMBIGUOUS',
                'message':f'm-ATM source must contain exactly one month for comparison with one BC settlement report; found {sorted(source_periods)}. Upload one month at a time.','rows':[]}
    # Guard against using a supplemental sheet from a different active transaction period.
    tx_path=TX/'latest_transactions.csv'
    if tx_path.exists():
        try:
            tx=pd.read_csv(tx_path,low_memory=False)
            date_col=next((c for c in ['transaction_date','date','txn_date'] if c in tx.columns),None)
            if date_col:
                tx_periods=set(pd.to_datetime(tx[date_col],errors='coerce').dropna().dt.strftime('%Y-%m').unique())
                src_periods=set(src['period'].dropna().astype(str).unique())
                if tx_periods and not (tx_periods & src_periods):
                    return {'available':False,'status':'PERIOD_MISMATCH','message':f'm-ATM source period(s) {sorted(src_periods)} do not match active transaction period(s) {sorted(tx_periods)}. Upload matching-period files.','rows':[]}
        except Exception:
            return {'available':False,'status':'PERIOD_VALIDATION_FAILED','message':'Could not validate the m-ATM source period against active transactions. Re-upload period-matched sources.','rows':[]}
    src['csp_id']=_clean_csp_ids(src['csp_id'])
    src['period']=src['period'].astype(str).str.strip()
    src['csp_name']=src.get('csp_name',pd.Series('',index=src.index)).fillna('').astype(str).str.strip()
    src['matm_transaction_count']=pd.to_numeric(src['matm_transaction_count'],errors='coerce')
    # Aggregate duplicate raw rows before applying CM060's CSP/month cap.
    srcg=src.groupby(['period','csp_id'],as_index=False).agg(
        csp_name=('csp_name','first'),
        matm_transaction_count=('matm_transaction_count','sum')
    )
    srcg['source_csp_id']=srcg['csp_id']
    srcg['identity_resolution']=srcg['csp_id'].map(
        lambda v: 'EXACT_CSP_ID' if re.match(r'^1A85\d{4}$',str(v),re.I) else 'UNRESOLVED_SOURCE_ID'
    )
    bc['csp_id']=_clean_csp_ids(bc['csp_id'])
    bc['type_norm']=bc['transaction_type'].astype(str).str.upper().str.replace(r'[^A-Z0-9]+',' ',regex=True).str.strip()
    wanted=bc['type_norm'].isin([MATM_TYPE,'INCENTIVE ON CASH TRANSACTIONS DONE THROUGH M ATMS','INCENTIVE ON CASH TRANSACTIONS DONE THROUGH M ATMS'])
    # Also allow the approved descriptive SBI rule wording after normalization.
    wanted |= bc['type_norm'].str.contains(r'INCENTIVE ON CASH TRANSACTIONS DONE THROUGH M ATMS|MATM CASH TRANSACTIONS INCENTIVE',regex=True,na=False)
    bc=bc[wanted].copy()
    # Resolve a noncanonical source ID only when its normalized CSP name maps
    # to exactly one official ID in this current-period BC m-ATM population.
    # This is an evidence-backed current upload join, not a permanent alias.
    def _norm_matm_name(value):
        return re.sub(r'[^A-Z0-9]+',' ',str(value or '').upper()).strip()
    if 'csp_name' in bc.columns and not bc.empty:
        name_candidates={}
        bc_names=bc.copy()
        bc_names['_name_norm']=bc_names['csp_name'].map(_norm_matm_name)
        for nm, group in bc_names.groupby('_name_norm'):
            ids=sorted(set(v for v in group['csp_id'].astype(str) if re.match(r'^1A85\d{4}$',v,re.I)))
            if nm and len(ids)==1:
                name_candidates[nm]=ids[0]
        for idx, row in srcg.iterrows():
            if not re.match(r'^1A85\d{4}$',str(row['csp_id']),re.I):
                candidate=name_candidates.get(_norm_matm_name(row.get('csp_name','')))
                if candidate:
                    srcg.at[idx,'csp_id']=candidate
                    srcg.at[idx,'identity_resolution']='EXACT_UNIQUE_CURRENT_BC_NAME'
        # An alias can collapse onto an existing official CSP row. Re-aggregate
        # source counts by month and resolved canonical ID before applying the cap.
        srcg=srcg.groupby(['period','csp_id'],as_index=False).agg(
            csp_name=('csp_name','first'),
            matm_transaction_count=('matm_transaction_count','sum'),
            source_csp_id=('source_csp_id',lambda x:';'.join(sorted(set(map(str,x))))),
            identity_resolution=('identity_resolution',lambda x:';'.join(sorted(set(map(str,x)))))
        )
    srcg['expected_incentive']=(srcg['matm_transaction_count']*MATM_RATE).clip(upper=MATM_CAP)
    bc[amount]=pd.to_numeric(bc[amount],errors='coerce')
    base_col=next((c for c in ['report_base','num_txns','num_txns_avg_bal','base'] if c in bc.columns),None)
    if base_col is None:
        base_col=next((c for c in bc.columns if 'base' in c or 'num_txn' in c or 'quantity' in c),None)
    if bc[amount].isna().any():
        return {'available':False,'status':'BC_AMOUNT_INVALID','message':'m-ATM BC rows contain missing/invalid actual commission.','rows':[]}
    if base_col:
        bc[base_col]=pd.to_numeric(bc[base_col],errors='coerce').fillna(0)
        actual=bc.groupby('csp_id',as_index=False).agg(bank_recognized_txns=(base_col,'sum'),actual_commission=(amount,'sum'))
    else:
        actual=bc.groupby('csp_id',as_index=False).agg(actual_commission=(amount,'sum'))
        actual['bank_recognized_txns']=pd.NA
    # Source is one-period per current upload. Collapse its period after guarding active transaction period.
    srcg=srcg.groupby('csp_id',as_index=False).agg(
        period=('period','first'),
        csp_name=('csp_name','first'),
        matm_transaction_count=('matm_transaction_count','sum'),
        expected_incentive=('expected_incentive','sum'),
        source_csp_id=('source_csp_id',lambda x:';'.join(sorted(set(map(str,x))))),
        identity_resolution=('identity_resolution',lambda x:';'.join(sorted(set(map(str,x)))))
    )
    out=srcg.merge(actual,on='csp_id',how='outer',indicator=True)
    out['csp_name']=out['csp_name'].fillna('')
    if 'identity_resolution' in out.columns:
        out['identity_resolution']=out['identity_resolution'].fillna('BC_ID_ONLY')
    else:
        out['identity_resolution']='BC_ID_ONLY'
    out['source_csp_id']=out.get('source_csp_id',pd.Series('',index=out.index)).fillna('')
    out['matm_transaction_count']=pd.to_numeric(out['matm_transaction_count'],errors='coerce').fillna(0)
    out['expected_incentive']=pd.to_numeric(out['expected_incentive'],errors='coerce').fillna(0)
    # Preserve whether a bank quantity was actually available before filling
    # display values; a missing quantity is not an exact count match.
    out['bank_count_available']=out['bank_recognized_txns'].notna()
    out['bank_recognized_txns']=pd.to_numeric(out['bank_recognized_txns'],errors='coerce').fillna(0)
    out['actual_commission']=pd.to_numeric(out['actual_commission'],errors='coerce').fillna(0)
    out['count_variance_bank_minus_source']=out['bank_recognized_txns']-out['matm_transaction_count']
    def _count_status(row):
        if row['_merge']=='left_only': return 'SOURCE ONLY'
        if row['_merge']=='right_only': return 'BC ONLY'
        if not bool(row.get('bank_count_available',False)): return 'COUNT EVIDENCE MISSING'
        return 'COUNT MATCH' if abs(float(row['count_variance_bank_minus_source']))<0.000001 else 'COUNT MISMATCH'
    out['count_status']=out.apply(_count_status,axis=1)
    out['variance_actual_minus_expected']=out['actual_commission']-out['expected_incentive']
    def _matm_status(row):
        unresolved = not bool(re.match(r'^1A85\d{4}$', str(row.get('csp_id','')), re.I))
        if row['_merge']=='right_only': return 'BC ONLY'
        if row['_merge']=='left_only':
            if unresolved: return 'SOURCE ID UNRESOLVED'
            return 'SHORT PAID' if row['expected_incentive']>0 else 'NO ACTIVITY'
        if abs(float(row['variance_actual_minus_expected']))<0.011:
            return 'MATCHED' if row['expected_incentive']>0 or row['actual_commission']>0 else 'NO ACTIVITY'
        return 'SHORT PAID' if row['variance_actual_minus_expected']<0 else 'EXCESS PAID'
    out['status']=out.apply(_matm_status,axis=1)
    expected_total=float(out['expected_incentive'].sum())
    actual_total=float(out['actual_commission'].sum())
    from app.services.control_kpi import active_csp_month_control_groups
    active_controls=active_csp_month_control_groups(out['expected_incentive'], out['actual_commission'])
    return _response({'available':True,'status':'READY','rule_id':'SBI-CM060','periods':sorted(src['period'].dropna().astype(str).unique().tolist()),'rule':{'rate_per_transaction':MATM_RATE,'monthly_cap':MATM_CAP},'summary':{'source_csp_controls':int(srcg.csp_id.nunique()),
        # KPI denominator must include only CSP-month controls with activity or a
        # bank-paid amount. Source roster rows with zero eligible transactions and
        # no BC payout are informational NO ACTIVITY rows, not failed controls.
        'control_groups':active_controls,'all_identity_rows':int(len(out)),'active_control_groups':active_controls,
        'matched':int((out.status=='MATCHED').sum()),
        'short_paid':int((out.status=='SHORT PAID').sum()),
        'excess_paid':int((out.status=='EXCESS PAID').sum()),
        'source_only':int(((out['_merge']=='left_only') & (out['expected_incentive']>0)).sum()),
        'no_activity':int((out.status=='NO ACTIVITY').sum()),
        'bc_only':int((out['_merge']=='right_only').sum()),
        'count_matched':int(((out['count_status']=='COUNT MATCH') & ((out['matm_transaction_count']>0)|(out['actual_commission']>0))).sum()),
        'count_mismatches':int(((out['count_status']=='COUNT MISMATCH') & ((out['matm_transaction_count']>0)|(out['actual_commission']>0))).sum()),
        'count_source_only':int(((out['count_status']=='SOURCE ONLY') & (out['matm_transaction_count']>0)).sum()),
        'count_bc_only':int(((out['count_status']=='BC ONLY') & (out['actual_commission']>0)).sum()),
        'source_transaction_count':int(src['matm_transaction_count'].sum()),
        'bank_recognized_transactions':int(out['bank_recognized_txns'].sum()),
        'count_variance_bank_minus_source':int(out['bank_recognized_txns'].sum()-src['matm_transaction_count'].sum()),
        'expected_total':round(expected_total,2),'actual_total':round(actual_total,2),
        'variance_actual_minus_expected':round(actual_total-expected_total,2),
        'match_rate':round((out.status=='MATCHED').sum()/active_controls*100,2) if active_controls else None,
        'count_match_rate':round(((out['count_status']=='COUNT MATCH') & ((out['matm_transaction_count']>0)|(out['actual_commission']>0))).sum()/active_controls*100,2) if active_controls else None},
        'rows':out.drop(columns=['_merge']).to_dict('records'),
        'note':'Expected = min(monthly CSP source transaction count × ₹3, ₹1,000), applied once per CSP/month after summing rows. Commission matching and transaction-count matching are reported separately; BC commission is actual-side evidence only.'})

@router.post('/tab-incentive')
async def tab_incentive(file: UploadFile = File(...), sheet_name: Optional[str] = Form(None)):
    """Upload monthly CSP-wise eligible TAB financial transaction counts; m-ATM is excluded by SBI rule."""
    try:
        content, sha = await _read(file, sheet_name, 'tab_incentive')
        raw = None; chosen = None; mapped = {}
        if file.filename.lower().endswith('.xlsx'):
            xl = excel_io.excel_file(content)
            names = [sheet_name] if sheet_name in xl.sheet_names else xl.sheet_names
            for nm in names:
                candidate = excel_io.read_excel(content, sheet_name=nm, engine='openpyxl')
                norm = {re.sub(r'[^a-z0-9]+','_',str(c).lower()).strip('_'): c for c in candidate.columns}
                if any(k in norm for k in ['csp_id','csp_code','csp_code_new','csp_id_code','csp_code_id','csp']) and any(('tab' in k and ('financial' in k or 'transaction' in k or 'count' in k)) or ('financial_transaction' in k) for k in norm):
                    raw=candidate; chosen=nm; break
                # Original source report has a title row and headers on row 4.
                # Scan a fixed header window: candidate was initially read with the default header, so its
                # dataframe length may be much smaller than the real worksheet row count.
                for hdr in range(0, min(20, max(len(candidate)+5, 20))):
                    try: test=excel_io.read_excel(content,sheet_name=nm,header=hdr,engine='openpyxl')
                    except Exception: continue
                    keys=[re.sub(r'[^a-z0-9]+',' ',str(c).lower()).strip() for c in test.columns]
                    if any(('csp code' in k or 'csp id' in k or k in ('csp','csp code new','csp id code','csp code id')) for k in keys) and any(('tab' in k and ('financial' in k or 'transaction' in k or 'count' in k)) or ('financial transaction' in k) or ('transaction count' in k) for k in keys):
                        raw=test; chosen=nm; break
                if raw is not None: break
            if raw is None: raise HTTPException(400,'TAB workbook requires CSP Code/ID, Month/Period, and TAB financial transaction count columns. Use the standardized TAB Incentive Upload sheet or upload the original report.')
        else:
            raw=pd.read_csv(BytesIO(content),low_memory=False)
        # Normalize source headers before alias mapping. The original SBI workbook
        # uses display headers such as `Month`, `CSP code`, and
        # `TAB financial transactions`; without normalization these valid columns
        # were not mapped to the canonical upload fields.
        raw=_clean_supplement_columns(raw)
        # Original monthly exports can use a period-bearing singular header such as
        # `TAB Transaction Sep 26`; map it deterministically instead of requiring
        # the exact standardized `TAB financial transactions` label.
        tab_period_columns = [c for c in raw.columns
                              if _month_from_text(c) and 'tab' in c
                              and any(token in c for token in ('transaction','txn','count','financial'))]
        if not any(c in raw.columns for c in ('tab_financial_transactions','tab_financial_transaction','tab_financial_transaction_count','tab_transaction_count','tab_transactions','tab_transaction','financial_transactions','financial_transaction','financial_transaction_count','eligible_transactions','transaction_count','transactions','txn_count','count')) and len(tab_period_columns) == 1:
            raw = raw.rename(columns={tab_period_columns[0]: 'tab_financial_transactions'})
            if not any(c in raw.columns for c in ('period','month','month_year','report_month')):
                raw['period'] = _month_from_text(tab_period_columns[0])
        df,mapped=_alias_columns(raw,{
            'period':['period','month','month_year','report_month'],
            'csp_id':['csp_id','csp_code','csp_code_new','csp_id_code','csp_code_id','csp'],
            'csp_name':['csp_name','name'],
            'tab_financial_transactions':['tab_financial_transactions','tab_financial_transaction','tab_financial_transaction_count','tab_transaction_count','tab_transactions','tab_transaction','financial_transactions','financial_transaction','financial_transaction_count','eligible_transactions','transaction_count','transactions','txn_count','count'],
            'monthly_cap':['monthly_cap','cap','monthly_cap_rs']})
        if 'period' not in df.columns:
            # A filename such as 'TAB Transaction Sep 26.xlsx' is an explicit period label.
            filename_period = _month_from_text(file.filename) or _active_single_month_period()
            if filename_period:
                df['period'] = filename_period
        if not {'period','csp_id','tab_financial_transactions'}.issubset(df.columns):
            raise HTTPException(400,'TAB source requires CSP Code/ID, an explicit Month/Period (column or filename), and TAB financial transaction count.')
        df['period']=df['period'].map(lambda x: str(x).strip() if re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',str(x).strip()) else _month_from_text(x))
        df['csp_id']=_clean_csp_ids(df['csp_id'])
        if 'csp_name' not in df: df['csp_name']=''
        df['csp_name']=df['csp_name'].fillna('').astype(str).str.strip()
        df['tab_financial_transactions']=pd.to_numeric(df['tab_financial_transactions'],errors='coerce')
        # The monthly cap is the permanent SBI rule (₹1,000), never a value from the uploaded file.
        # A different cap in the source is reported, not used (V62.6.210).
        source_cap=pd.to_numeric(df['monthly_cap'],errors='coerce') if 'monthly_cap' in df else pd.Series(pd.NA,index=df.index,dtype='Float64')
        tab_cap_overrides=int((source_cap.notna() & source_cap.ne(TAB_CAP)).sum())
        df['monthly_cap']=TAB_CAP
        # Some prepared source workbooks include a grand-total footer row (e.g. blank
        # Month/CSP with 72 transactions and ₹360). Exclude it only when its count
        # exactly equals the sum of valid CSP detail rows; otherwise leave it for
        # validation to reject instead of silently discarding questionable records.
        valid_detail = df['period'].notna() & df['csp_id'].str.match(r'^1A85\d{4}$',na=False) & df['tab_financial_transactions'].notna()
        detail_total = float(df.loc[valid_detail,'tab_financial_transactions'].sum())
        is_total_label = df['csp_id'].astype(str).str.strip().str.upper().isin({'TOTAL','GRAND TOTAL','SUBTOTAL','OVERALL TOTAL'})
        summary_footer = df['tab_financial_transactions'].notna() & df['tab_financial_transactions'].eq(detail_total) & (detail_total > 0) & ((df['period'].isna() & df['csp_id'].eq('')) | (is_total_label & ~df['csp_id'].str.match(r'^1A85\\d{4}$',na=False)))
        if summary_footer.any():
            df = df.loc[~summary_footer].copy()
        invalid=df['period'].isna() | ~df['csp_id'].str.match(r'^1A85\d{4}$',na=False) | df['tab_financial_transactions'].isna() | (df['tab_financial_transactions']<0) | (df['tab_financial_transactions']%1!=0)
        if invalid.any(): raise HTTPException(400,f'Invalid TAB rows (period, official CSP ID, non-negative whole transaction count required): {df.loc[invalid].head(8).to_dict("records")}')
        if df.duplicated(['period','csp_id']).any():
            dup=df.loc[df.duplicated(['period','csp_id'],keep=False),['period','csp_id']].to_dict('records')
            raise HTTPException(400,f'Duplicate CSP/month rows. Resolve before upload: {dup[:10]}')
        df['expected_incentive']=(df['tab_financial_transactions']*TAB_RATE).clip(upper=df['monthly_cap'])
        df['transaction_type']=TAB_TYPE; df['source_file']=file.filename
        out=df[['period','csp_id','csp_name','tab_financial_transactions','expected_incentive','monthly_cap','transaction_type','source_file']]
        out.to_csv(TAB_COUNTS,index=False)
        periods=sorted(out.period.unique().tolist())
        TAB_META.write_text(json.dumps({'filename':file.filename,'sha256':sha,'sheet_name':chosen,'periods':periods,'rows':len(out),'mapped_columns':mapped,'rate_per_transaction':TAB_RATE,'monthly_cap':TAB_CAP,'m_atm_excluded':True,'rule_id':'SBI-TAB-INCENTIVE-001','parser_version':'tab-incentive-v3-period-agnostic-header-normalization'},indent=2),encoding='utf-8')
        clear_cache()
        return _response({'file_type':'tab_incentive','filename':file.filename,'sheet_name':chosen,'saved':True,'validation':{'valid':True,'rows':len(out),'periods':periods,'mapped_columns':mapped,'rate_per_eligible_transaction':TAB_RATE,'monthly_cap':TAB_CAP,'source_monthly_cap_rows_ignored':tab_cap_overrides,'warnings':([f'{tab_cap_overrides} row(s) carried a monthly cap different from the SBI rule; the SBI cap of Rs {TAB_CAP:,.0f} was applied.'] if tab_cap_overrides else []),'expected_total':round(float(out.expected_incentive.sum()),2),'csp_month_controls':len(out),'m_atm_excluded':True,'rule_id':'SBI-TAB-INCENTIVE-001','note':'Permanent rule: ₹5 per eligible TAB financial transaction excluding m-ATM, capped at ₹1,000 per CSP per month.'}})
    except HTTPException: raise
    except Exception as e: raise HTTPException(400,f'TAB incentive upload failed: {e}')

@router.get('/tab-incentive/reconciliation')
def tab_incentive_reconciliation():
    """Reconcile uploaded TAB incentive expected values to exact CSP IDs and matching BC incentive rows."""
    if not TAB_COUNTS.exists(): return {'available':False,'status':'SOURCE_MISSING','message':'Upload current-period TAB incentive CSP/count sheet.','rows':[]}
    src=pd.read_csv(TAB_COUNTS,dtype={'csp_id':str},low_memory=False)
    if not (CM/'latest_commission.csv').exists(): return {'available':False,'status':'BC_REPORT_MISSING','message':'Upload the matching-period BC Commission Report.','rows':[]}
    bc=pd.read_csv(CM/'latest_commission.csv',dtype={'csp_id':str},low_memory=False)
    if not {'csp_id','transaction_type'}.issubset(bc.columns): return {'available':False,'status':'BC_SCHEMA_INVALID','message':'BC commission data requires CSP ID and transaction type.','rows':[]}
    amount='actual_commission' if 'actual_commission' in bc.columns else ('commission' if 'commission' in bc.columns else None)
    if not amount: return {'available':False,'status':'BC_SCHEMA_INVALID','message':'BC commission data requires actual commission amount.','rows':[]}
    bc['csp_id']=_clean_csp_ids(bc.csp_id); bc['type_norm']=bc.transaction_type.astype(str).str.upper().str.replace(r'[^A-Z0-9]+',' ',regex=True).str.strip()
    wanted=TAB_TYPE.replace('_',' ')
    bc=bc[bc.type_norm.str.contains(r'TAB.*TRANSACTION.*INCENTIVE|INCENTIVE.*TAB.*TRANSACTION',regex=True,na=False)].copy()
    # Period-safe matching: if a multi-month TAB source is uploaded, require a period
    # field in the BC rows instead of cross-matching a CSP's payment across months.
    source_periods=sorted(src['period'].dropna().astype(str).unique().tolist())
    period_col=next((c for c in ['period','month','report_month'] if c in bc.columns),None)
    if len(source_periods)>1 and period_col is None:
        return {'available':False,'status':'PERIOD_EVIDENCE_REQUIRED','message':'The TAB source contains multiple months but the BC commission rows do not expose a month/period column. Upload a period-specific BC report or provide explicit period mapping; payments will not be cross-matched across months.','rows':[]}
    if period_col is not None:
        bc[period_col]=bc[period_col].map(lambda x: str(x).strip() if re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',str(x).strip()) else _month_from_text(x))
    bc[amount]=pd.to_numeric(bc[amount],errors='coerce')
    if bc[amount].isna().any(): return {'available':False,'status':'BC_AMOUNT_INVALID','message':'TAB incentive BC rows contain missing/invalid actual commission values.','rows':[]}
    if period_col is not None:
        actual=bc.groupby([period_col,'csp_id'],as_index=False)[amount].sum().rename(columns={period_col:'period',amount:'actual_commission'})
        out=src.merge(actual,on=['period','csp_id'],how='left')
    else:
        if len(source_periods)>1:
            return {'available':False,'status':'PERIOD_EVIDENCE_REQUIRED','message':'Multi-month source requires period-specific actual commission evidence.','rows':[]}
        actual=bc.groupby('csp_id',as_index=False)[amount].sum().rename(columns={amount:'actual_commission'})
        out=src.merge(actual,on='csp_id',how='left')
    out['actual_commission']=out.actual_commission.fillna(0.0)
    out['difference_bank_minus_expected']=out.actual_commission-out.expected_incentive
    out['status']=out.apply(lambda r:'Matched' if abs(float(r.actual_commission)-float(r.expected_incentive))<0.011 else ('Short Paid' if r.actual_commission<r.expected_incentive else 'Excess Paid'),axis=1)
    out['variance']=out.difference_bank_minus_expected
    total_expected=float(out.expected_incentive.sum()); total_actual=float(out.actual_commission.sum()); matched=int((out.status=='Matched').sum())
    periods=sorted(out.period.dropna().astype(str).unique().tolist())
    return _response({'available':True,'status':'READY','rule_id':'SBI-TAB-INCENTIVE-001','rule':{'rate_per_transaction':TAB_RATE,'monthly_cap':TAB_CAP,'m_atm_excluded':True},'periods':periods,'summary':{'control_groups':len(out),'matched':matched,'short_paid':int((out.status=='Short Paid').sum()),'excess_paid':int((out.status=='Excess Paid').sum()),'expected_total':round(total_expected,2),'actual_total':round(total_actual,2),'variance_actual_minus_expected':round(total_actual-total_expected,2),'match_rate':round(matched/len(out)*100,2) if len(out) else None},'rows':out.to_dict('records'),'note':'Missing actual TAB incentive rows are treated as zero paid for this uploaded CSP/month control; verify the BC report period and transaction-type label before treating this as final settlement.'})


# SBI Loan Lead Generation commission rule. Commission is calculated on sanction limit;
# if the uploaded lead sheet does not contain that base, expected commission remains unresolved.
LOAN_LEADS_PATH=SUPPLEMENTAL/'latest_loan_lead_generation.csv'
LOAN_LEADS_META=SUPPLEMENTAL/'latest_loan_lead_generation_metadata.json'

def _loan_lead_product(value):
    t=re.sub(r'[^A-Z0-9]+','_',str(value or '').upper()).strip('_')
    if t in ('HOUSING_LOAN_LEAD','HOME_LOAN_LEAD','HOUSING_LOAN'): return 'HOME LOAN'
    if t in ('VEHICLE_LOAN_LEAD','CAR_LOAN_LEAD','VEHICLE_LOAN'): return 'VEHICLE LOAN'
    if t in ('MUDRA_LOAN_LEAD','MUDRA_LOAN'): return 'MUDRA LOAN'
    if t in ('PERSONAL_LOAN_LEAD','PERSONAL_LOAN'): return 'PERSONAL LOAN'
    # OTHER_P_SEG_LOAN_LEAD is broader than the SBI rule's P-Segment Gold Loan.
    # Do not silently treat it as Gold Loan without an approved product crosswalk.
    if t in ('P_SEGMENT_GOLD_LOAN_LEAD','GOLD_LOAN_LEAD'): return 'P-SEGMENT GOLD LOAN'
    if t in ('AGRI_GOLD_LOAN_LEAD','AGRICULTURE_GOLD_LOAN_LEAD'): return 'AGRI GOLD LOAN'
    # AGRI_LOAN_LEAD is broader than the SBI rule's Agri Gold Loan product; do not guess its product mapping.
    return None

@router.post('/loan-lead-generation')
async def loan_lead_generation(file: UploadFile = File(...), sheet_name: Optional[str] = Form(None)):
    """Upload period-specific loan leads. Never infer sanction limit from lead amount/status."""
    try:
        content, sha = await _read(file, sheet_name, 'loan_lead_generation')
        frames=[]; chosen=None; header_row=None
        if file.filename.lower().endswith('.xlsx'):
            xl=excel_io.excel_file(content)
            names=[sheet_name] if sheet_name in xl.sheet_names else xl.sheet_names
            for nm in names:
                for hdr in range(0, min(15, 15)):
                    try: test=excel_io.read_excel(content,sheet_name=nm,header=hdr,engine='openpyxl')
                    except Exception: continue
                    test=_clean_supplement_columns(test)
                    cols=set(test.columns)
                    if (('lead_id' in cols or 'leadid' in cols) and ('loan_type' in cols or 'loan_product' in cols) and ('csp_code' in cols or 'csp_id' in cols)):
                        frames=[test]; chosen=nm; header_row=hdr; break
                if frames: break
            if not frames: raise HTTPException(400,'Loan Lead workbook requires Lead ID, Loan type/product, Lead date, Status and CSP code columns.')
            raw=frames[0]
        else:
            raw=pd.read_csv(BytesIO(content),low_memory=False); raw=_clean_supplement_columns(raw)
            chosen=None; header_row=0
        raw=_clean_supplement_columns(raw)
        # Original monthly exports can use a period-bearing singular header such as
        # `TAB Transaction Sep 26`; map it deterministically instead of requiring
        # the exact standardized `TAB financial transactions` label.
        tab_period_columns = [c for c in raw.columns
                              if _month_from_text(c) and 'tab' in c
                              and any(token in c for token in ('transaction','txn','count','financial'))]
        if not any(c in raw.columns for c in ('tab_financial_transactions','tab_financial_transaction','tab_financial_transaction_count','tab_transaction_count','tab_transactions','tab_transaction','financial_transactions','financial_transaction','financial_transaction_count','eligible_transactions','transaction_count','transactions','txn_count','count')) and len(tab_period_columns) == 1:
            raw = raw.rename(columns={tab_period_columns[0]: 'tab_financial_transactions'})
            if not any(c in raw.columns for c in ('period','month','month_year','report_month')):
                raw['period'] = _month_from_text(tab_period_columns[0])
        df,mapped=_alias_columns(raw,{
            'lead_id':['lead_id','leadid','application_id','reference_number'],
            'lead_date':['lead_date','date','created_date','created_on'],
            'loan_type':['loan_type','loan_product','product_type','lead_type'],
            'status':['status_latest','latest_status','status','lead_status'],
            'csp_id':['csp_code','csp_id','csp_code_new','csp'],
            'csp_name':['csp_name','name'],
            'sanction_limit':['sanction_limit','sanctioned_amount','loan_sanction_amount','sanction_amount'],
            'gst_rate':['gst_rate','gst_percent','gst_percentage']})
        required={'lead_id','loan_type','status','csp_id'}
        if not required.issubset(df.columns): raise HTTPException(400,f'Loan Lead source missing required columns: {sorted(required-set(df.columns))}')
        df['lead_id']=df['lead_id'].astype(str).str.strip()
        # Official exports may append a summary row such as TOTAL LEADS. It is not a lead record.
        # Drop only clearly labelled aggregate/footer rows; keep other malformed rows for validation.
        summary_ids = df['lead_id'].str.strip().str.casefold().isin({'total leads','total lead','grand total','total','overall total'})
        if summary_ids.any():
            df = df.loc[~summary_ids].copy()
        df['csp_id']=_clean_csp_ids(df['csp_id'])
        df['loan_type_raw']=df['loan_type'].fillna('').astype(str).str.strip()
        df['loan_product']=df['loan_type_raw'].map(_loan_lead_product)
        df['status']=df['status'].fillna('').astype(str).str.strip()
        if 'csp_name' not in df: df['csp_name']=''
        df['csp_name']=df['csp_name'].fillna('').astype(str).str.strip()
        if 'lead_date' in df:
            df['lead_date']=pd.to_datetime(df['lead_date'],errors='coerce',dayfirst=True)
            df['period']=df['lead_date'].dt.strftime('%Y-%m')
        else:
            df['period']=None
        # Always use numeric dtypes for optional numeric columns. An all-missing
        # object Series (pd.NA) raises TypeError on comparisons such as < 0.
        if 'sanction_limit' in df:
            df['sanction_limit']=pd.to_numeric(df['sanction_limit'],errors='coerce').astype('float64')
        else:
            df['sanction_limit']=pd.Series(float('nan'), index=df.index, dtype='float64')
        if 'gst_rate' in df:
            df['gst_rate']=pd.to_numeric(df['gst_rate'],errors='coerce').astype('float64')
        else:
            df['gst_rate']=pd.Series(float('nan'), index=df.index, dtype='float64')
        # Lead ID is the primary identity; duplicates are blocked rather than silently double counted.
        invalid=df['lead_id'].isin(['','nan','None']) | df['csp_id'].eq('') | df['loan_type_raw'].eq('') | df['status'].eq('')
        if invalid.any(): raise HTTPException(400,f'Invalid Loan Lead rows (Lead ID, CSP ID, loan type and status required): {df.loc[invalid].head(8).to_dict("records")}')
        if df['lead_id'].duplicated().any():
            dup=df.loc[df['lead_id'].duplicated(keep=False),'lead_id'].tolist()
            raise HTTPException(400,f'Duplicate Lead IDs detected; deduplicate before upload: {dup[:10]}')
        if df['period'].isna().any(): raise HTTPException(400,'Some lead dates are missing or invalid. Correct the source dates before uploading.')
        if (df['sanction_limit'].dropna()<0).any(): raise HTTPException(400,'Sanction limit cannot be negative.')
        df['rate']=df['loan_product'].map({'HOME LOAN':.005,'VEHICLE LOAN':.005,'MUDRA LOAN':.0025,'PERSONAL LOAN':.001,'P-SEGMENT GOLD LOAN':.001,'AGRI GOLD LOAN':.001})
        df['sanction_evidence']=df['status'].str.contains(r'sanction',case=False,na=False)
        calc_ok=df['sanction_evidence'] & df['sanction_limit'].notna() & df['loan_product'].notna() & df['rate'].notna()
        df['expected_base_commission']=pd.Series(float('nan'), index=df.index, dtype='float64')
        df.loc[calc_ok,'expected_base_commission']=(df.loc[calc_ok,'sanction_limit']*df.loc[calc_ok,'rate']).round(2)
        df['gst_amount']=pd.Series(float('nan'), index=df.index, dtype='float64')
        gst_ok=calc_ok & df['gst_rate'].notna()
        df.loc[gst_ok,'gst_amount']=(df.loc[gst_ok,'expected_base_commission']*df.loc[gst_ok,'gst_rate']/100).round(2)
        df['calculation_status']='SANCTION_LIMIT_REQUIRED'
        df.loc[df['loan_product'].isna(),'calculation_status']='LOAN_PRODUCT_MAPPING_REQUIRED'
        df.loc[df['loan_product'].notna() & ~df['sanction_evidence'],'calculation_status']='SANCTION_EVIDENCE_REQUIRED'
        df.loc[calc_ok & df['gst_rate'].isna(),'calculation_status']='BASE_CALCULATED_GST_RATE_REQUIRED'
        df.loc[gst_ok,'calculation_status']='BASE_AND_GST_CALCULATED'
        df['rule_rate']=df['rate']
        df['source_file']=file.filename
        out=df[['period','lead_id','lead_date','csp_id','csp_name','loan_type_raw','loan_product','status','sanction_limit','rule_rate','expected_base_commission','gst_rate','gst_amount','calculation_status','source_file']].copy()
        out['lead_date']=pd.to_datetime(out['lead_date'],errors='coerce').dt.strftime('%Y-%m-%d')
        out.to_csv(LOAN_LEADS_PATH,index=False)
        periods=sorted(out.period.dropna().unique().tolist())
        summary={'rows':len(out),'periods':periods,'unique_csp_count':int(out.csp_id.nunique()),'unique_lead_count':int(out.lead_id.nunique()),'product_counts':{('UNMAPPED' if pd.isna(k) else str(k)):int(v) for k,v in out.groupby('loan_product',dropna=False).size().items()},'sanction_limit_rows':int(out.sanction_limit.notna().sum()),'base_calculated_rows':int(out.expected_base_commission.notna().sum()),'unresolved_sanction_limit_rows':int(out.sanction_limit.isna().sum()),'sanction_evidence_missing_rows':int((~df['sanction_evidence']).sum()),'unmapped_product_rows':int((out.calculation_status=='LOAN_PRODUCT_MAPPING_REQUIRED').sum()),'expected_base_commission_total':None if out.expected_base_commission.notna().sum()==0 else round(float(pd.to_numeric(out.expected_base_commission,errors='coerce').sum()),2),'gst_rate_source':'Only calculated when explicit GST rate is supplied in uploaded file; screenshot rule does not specify GST percentage.'}
        LOAN_LEADS_META.write_text(json.dumps({'filename':file.filename,'sha256':sha,'sheet_name':chosen,'header_row_zero_based':header_row,'periods':periods,'rows':len(out),'mapped_columns':mapped,'summary':summary,'rule_id':'SBI-LOAN-LEAD-GENERATION-001','parser_version':'loan-lead-v1-sanction-limit-only'},indent=2,default=str),encoding='utf-8')
        meta=load_metadata(); meta['loan_lead_generation']={'filename':file.filename,'sha256':sha,'periods':periods,'rows':len(out),'uploaded_at':__import__('datetime').datetime.now().isoformat()}; from app.services.upload_metadata import _write; _write(meta)
        clear_cache()
        return _response({'file_type':'loan_lead_generation','filename':file.filename,'sheet_name':chosen,'saved':True,'validation':{'valid':True,**summary,'mapped_columns':mapped,'rule_id':'SBI-LOAN-LEAD-GENERATION-001','note':'Expected commission is calculated only when sanction limit and sanction evidence are present. GST is not guessed.'}})
    except HTTPException: raise
    except Exception as e: raise HTTPException(400,f'Loan Lead Generation upload failed: {e}')

@router.get('/loan-lead-generation/reconciliation')
def loan_lead_generation_reconciliation():
    if not LOAN_LEADS_PATH.exists():
        return {'available':False,'status':'SOURCE_MISSING','message':'Upload current-period Loan Lead Generation sheet.','rows':[],'match_rows':[]}
    try:
        from app.services.loan_lead_reconciliation import build_reconciliation
        df=pd.read_csv(LOAN_LEADS_PATH,low_memory=False)
        upload_meta=load_metadata()
        commission_meta=upload_meta.get('commission') or {}
        commission_path=CM/'latest_commission.csv'
        commission_df=pd.read_csv(commission_path,dtype={'csp_id':str},low_memory=False) if commission_path.exists() else pd.DataFrame()
        return build_reconciliation(df,commission_df,commission_meta)
    except Exception as e:
        return {'available':False,'status':'ERROR','message':str(e),'rows':[],'match_rows':[]}
