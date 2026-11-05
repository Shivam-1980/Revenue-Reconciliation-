from pathlib import Path
from io import BytesIO
import calendar
import re
import pandas as pd
from app.services import excel_io

BASE_DIR = Path(__file__).resolve().parents[1]
RURAL_DIR = BASE_DIR / 'data' / 'rural_csp'
RURAL_MASTER_PATH = RURAL_DIR / 'latest_rural_csp_master.csv'
TXN_MAPPING_PATH = RURAL_DIR / 'rural_transaction_type_mapping.csv'

# SBI Rural Commission Rule — Rural CSP (Incentive). Kept as explicit constants so the
# financial eligibility rule is auditable and cannot be confused with a
# month-specific August calculation.
RURAL_RULE_CODE = 'SBI-RULE-9'
RURAL_RULE_NAME = 'Rural CSP (Incentive)'
RURAL_INCENTIVE_AMOUNT = 2000.0
RURAL_MIN_LOGIN_DAYS = 20
RURAL_MIN_PMJDY = 50
RURAL_MIN_TXN = 100
RURAL_NOT_APPLICABLE_AREAS = {'URBAN', 'METRO', 'URBAN/METRO'}


def norm(v):
    if pd.isna(v):
        return ''
    return ' '.join(str(v).strip().upper().split())


def _normalize_columns(df):
    out = df.copy()
    out.columns = (out.columns.astype(str).str.strip().str.lower()
                   .str.replace(r'[^a-z0-9]+', '_', regex=True).str.strip('_'))
    return out


def _period_from_login_header(columns):
    patterns = [
        re.compile(r'total[\s_]*login[\s_]*day[\s_]*\(?[\s_]*([A-Za-z]{3,9})[\'\-_/\s_]*(\d{2,4})[\s_]*\)?', re.I),
        re.compile(r'login.*?([A-Za-z]{3,9})[\'\-_/\s_]*(\d{2,4})', re.I),
        re.compile(r'([A-Za-z]{3,9})[_\-\s]+(\d{2,4})', re.I),
    ]
    for col in columns:
        raw = str(col).strip()
        for pat in patterns:
            m = pat.search(raw)
            if not m:
                continue
            mon, year = m.group(1), m.group(2)
            try:
                parsed = pd.to_datetime(mon, format='%B', errors='coerce')
                if pd.isna(parsed):
                    parsed = pd.to_datetime(mon, format='%b', errors='coerce')
                month = int(parsed.month) if pd.notna(parsed) else None
            except Exception:
                month = None
            if not month:
                continue
            y = int(year)
            if y < 100:
                y += 2000
            start = f'{y:04d}-{month:02d}-01'
            end = f'{y:04d}-{month:02d}-{calendar.monthrange(y, month)[1]:02d}'
            return f'{y:04d}-{month:02d}', start, end, raw
    return None, None, None, None


def _find_sheet_and_header(content):
    xl = excel_io.excel_file(content)
    for sheet in xl.sheet_names:
        raw = excel_io.read_excel(content, sheet_name=sheet, header=None, engine='openpyxl')
        for i in range(min(len(raw), 30)):
            vals = [norm(x) for x in raw.iloc[i].tolist()]
            has_id = any(re.sub(r'[^A-Z0-9]+', '_', v).strip('_') in {'CSP_ID','CSP_CODE','CSP_CODE_NEW','CSP','CSP_ID_CODE','CSP_CODE_ID'} for v in vals)
            has_login = any(('TOTAL LOGIN DAY' in v or ('LOGIN' in v and 'DAY' in v)) for v in vals)
            if has_id and has_login:
                return sheet, i
    # Distinguish a bank-paid commission report from the required eligibility roster.
    # A paid amount is not evidence of login days and must never be substituted for it.
    for sheet in xl.sheet_names:
        sample = excel_io.read_excel(content, sheet_name=sheet, nrows=8, engine='openpyxl')
        normalized = [re.sub(r'[^a-z0-9]+', '_', str(c).strip().lower()).strip('_') for c in sample.columns]
        has_csp = any(c in {'csp_id','csp_code','csp_code_new','csp'} for c in normalized)
        has_paid_amount = any(('rural_commission' in c or 'commission_rs' in c or 'commission_amount' in c) for c in normalized)
        if has_csp and has_paid_amount:
            raise ValueError('This workbook is a Rural Commission paid-amount report (CSP Code + Rural Commission (Rs)), not the required Rural CSP eligibility roster. Upload the current-period roster containing CSP ID and Total Login Day <Month-Year>. The paid amount cannot be used as login-day evidence.')
    raise ValueError('Could not find Rural CSP sheet with CSP ID and Total Login Day (<month>) columns.')


def parse_rural_csp_workbook(content, filename='Rural CSP'):
    sheet, header = _find_sheet_and_header(content)
    df = excel_io.read_excel(content, sheet_name=sheet, header=header, engine='openpyxl')
    df = _normalize_columns(df)
    aliases = {
        'csp_id': ['csp_id', 'csp_code', 'csp_code_new', 'csp_id_code', 'csp_code_id', 'csp'],
        'csp_name': ['csp_name', 'name'],
        'csp_category': ['csp_category', 'category'],
        'relationship_manager': ['relationship_manager', 'rm'],
    }
    ren = {}
    for dest, candidates in aliases.items():
        for c in candidates:
            if c in df.columns:
                ren[c] = dest
                break
    df = df.rename(columns=ren)
    login_cols = [c for c in df.columns if 'total_login_day' in c or ('login' in c and 'day' in c)]
    if 'csp_id' not in df.columns or not login_cols:
        raise ValueError('Rural CSP file must contain CSP ID and a month-specific Total Login Day column.')
    login_col = login_cols[0]
    period, period_start, period_end, login_header = _period_from_login_header(df.columns)
    if not period:
        raise ValueError(f'Could not determine period from login-day column: {login_col}')
    out = pd.DataFrame()
    out['csp_id'] = df['csp_id'].map(norm)
    out['csp_name'] = df.get('csp_name', pd.Series('', index=df.index)).map(norm)
    out['csp_category'] = df.get('csp_category', pd.Series('', index=df.index)).map(norm)
    out['relationship_manager'] = df.get('relationship_manager', pd.Series('', index=df.index)).map(norm)
    out['login_days'] = pd.to_numeric(df[login_col], errors='coerce')
    out['period'] = period
    out = out[out['csp_id'].str.match(r'^1A85\d{4}$', na=False)].copy()
    duplicate_ids = out.loc[out['csp_id'].duplicated(keep=False), 'csp_id'].unique().tolist()
    if duplicate_ids:
        raise ValueError(f'Rural CSP file contains duplicate CSP IDs; resolve duplicate rows before upload: {duplicate_ids[:10]}')
    if out.empty:
        raise ValueError('Rural CSP file contains no valid CSP IDs matching 1A85xxxx.')
    return out, {
        'valid': True,
        'rows': int(len(out)),
        'sheet_name': sheet,
        'header_row_zero_based': header,
        'period': period,
        'period_start': period_start,
        'period_end': period_end,
        'login_column': login_header or login_col,
        'mapped_columns': ren,
        'parser_version': '1.0.0-rural-csp-generic',
        'source_file': filename,
        'missing_login_days': int(out['login_days'].isna().sum()),
        'duplicate_csp_rows_removed': 0,
    }



def parse_rural_csp_csv(content, filename='Rural CSP CSV'):
    """Parse a month-labelled Rural CSP CSV using the same explicit source fields as XLSX."""
    from io import BytesIO
    raw = pd.read_csv(BytesIO(content), encoding='utf-8-sig')
    period, period_start, period_end, login_header = _period_from_login_header(raw.columns)
    if not period:
        raise ValueError('Could not determine month/year from Total Login Day (<month>) column.')
    df = _normalize_columns(raw)
    aliases = {
        'csp_id': ['csp_id', 'csp_code', 'csp_code_new', 'csp_id_code', 'csp_code_id', 'csp'],
        'csp_name': ['csp_name', 'name'],
        'csp_category': ['csp_category', 'category'],
        'relationship_manager': ['relationship_manager', 'rm'],
    }
    ren = {}
    for dest, candidates in aliases.items():
        for c in candidates:
            if c in df.columns:
                ren[c] = dest
                break
    df = df.rename(columns=ren)
    login_cols = [c for c in df.columns if 'total_login_day' in c or ('login' in c and 'day' in c)]
    if 'csp_id' not in df.columns or not login_cols:
        raise ValueError('Rural CSP CSV must contain CSP ID and a month-specific Total Login Day column.')
    out = pd.DataFrame(index=df.index)
    out['csp_id'] = df['csp_id'].map(norm)
    out['csp_name'] = df.get('csp_name', pd.Series('', index=df.index)).map(norm)
    out['csp_category'] = df.get('csp_category', pd.Series('', index=df.index)).map(norm)
    out['relationship_manager'] = df.get('relationship_manager', pd.Series('', index=df.index)).map(norm)
    out['login_days'] = pd.to_numeric(df[login_cols[0]], errors='coerce')
    out['period'] = period
    out = out[out['csp_id'].str.match(r'^1A85\d{4}$', na=False)].copy()
    duplicates = out.loc[out['csp_id'].duplicated(keep=False), 'csp_id'].unique().tolist()
    if duplicates:
        raise ValueError(f'Rural CSP CSV contains duplicate CSP IDs; resolve duplicate rows before upload: {duplicates[:10]}')
    if out.empty:
        raise ValueError('Rural CSP CSV contains no valid CSP IDs matching 1A85xxxx.')
    return out, {
        'valid': True, 'rows': int(len(out)), 'sheet_name': None,
        'period': period, 'period_start': period_start, 'period_end': period_end,
        'login_column': login_header or login_cols[0], 'mapped_columns': ren,
        'parser_version': '1.1.0-rural-csp-csv-generic', 'source_file': filename,
        'missing_login_days': int(out['login_days'].isna().sum()),
        'duplicate_csp_rows_removed': 0
    }

def save_rural_master(df):
    RURAL_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(RURAL_MASTER_PATH, index=False)


def load_rural_master():
    if not RURAL_MASTER_PATH.exists():
        return pd.DataFrame(columns=['csp_id','csp_name','csp_category','relationship_manager','login_days','period'])
    d = pd.read_csv(RURAL_MASTER_PATH, dtype=str).fillna('')
    for c in ['csp_id','csp_name','csp_category','relationship_manager','period']:
        if c in d:
            d[c] = d[c].map(norm)
    d['login_days'] = pd.to_numeric(d.get('login_days'), errors='coerce')
    return d


def load_txn_mapping():
    if not TXN_MAPPING_PATH.exists():
        return pd.DataFrame(columns=['transaction_type','count_as_txn','reason'])
    d = pd.read_csv(TXN_MAPPING_PATH, dtype=str).fillna('')
    d['transaction_type'] = d['transaction_type'].map(norm)
    d['count_as_txn'] = d['count_as_txn'].map(norm)
    d['reason'] = d['reason'].astype(str)
    return d


def _bank_area_by_csp(commission):
    if commission is None or commission.empty or 'channel' not in commission.columns:
        return {}
    c = commission.copy()
    c['csp_id'] = c['csp_id'].map(norm)
    c['channel'] = c['channel'].map(norm)
    # Prefer an unambiguous area. Conflicts are retained as unresolved rather than guessed.
    out = {}
    for csp, g in c.groupby('csp_id'):
        vals = set(g['channel'].dropna().tolist()) - {''}
        if len(vals) == 1:
            out[csp] = next(iter(vals))
        elif vals:
            out[csp] = 'CONFLICT'
    return out


def reconcile_rural_commission(commission, transaction_month=None, rural_master=None, txn_mapping=None):
    """Reconcile SBI Rural Commission Rule — Rural CSP (Incentive).

    Source rule (as supplied by the user):
      Condition 1: ID must be logged-in minimum 20 days.
      Condition 2: subject to opening of minimum 50 PMJDY / 100 TXN per month or both.
      Incentive: ₹2,000.
      Urban/Metro: Not Applicable.

    Deterministic eligibility: Condition 1 MUST pass AND Condition 2 MUST pass,
    where Condition 2 is (PMJDY >= 50 OR approved Count-as-TXN >= 100).
    Urban/Metro is explicitly Not Applicable. If the BC source explicitly identifies
    a CSP as Urban/Metro, no Rural incentive is expected for that CSP. Conflicting
    geography is unresolved and the expected amount is left blank (not guessed).
    The current-period Rural CSP source remains the population source; this rule is
    period-agnostic and applies to each uploaded calendar month.
    """
    master = rural_master if rural_master is not None else load_rural_master()
    mapping = txn_mapping if txn_mapping is not None else load_txn_mapping()
    if master is None or master.empty:
        return {'available': False, 'status': 'RURAL_CSP_SOURCE_REQUIRED', 'message': 'Upload the current-period Rural CSP list with Total Login Day (<month>).', 'rows': [], 'summary': {}}
    if mapping is None or mapping.empty:
        return {'available': False, 'status': 'RURAL_TXN_MAPPING_REQUIRED', 'message': 'Approved Rural Commission transaction-type mapping is missing or empty; eligibility cannot be calculated safely.', 'rows': [], 'summary': {}}
    # A transaction type with conflicting Y/N mapping is unsafe for a financial
    # threshold. Do not let a set() silently turn a conflict into an eligible count.
    mapping_check = mapping.copy()
    mapping_check['transaction_type'] = mapping_check['transaction_type'].map(norm)
    mapping_check['count_as_txn'] = mapping_check['count_as_txn'].map(norm)
    conflicts = []
    for typ, grp in mapping_check.groupby('transaction_type'):
        vals = set(grp['count_as_txn'].dropna().tolist()) - {''}
        if len(vals) > 1:
            conflicts.append(typ)
    if conflicts:
        return {'available': False, 'status': 'RURAL_TXN_MAPPING_CONFLICT', 'message': f'Conflicting Y/N Rural Commission transaction mapping for: {", ".join(sorted(conflicts)[:20])}.', 'rows': [], 'summary': {'conflicting_transaction_types': sorted(conflicts)}}
    periods = set(master['period'].dropna().map(norm)) if 'period' in master else set()
    if transaction_month and periods and periods != {transaction_month}:
        return {'available': False, 'status': 'PERIOD_MISMATCH', 'message': f'Rural CSP source period {sorted(periods)} does not match transaction period {transaction_month}.', 'rows': [], 'summary': {}}
    if not transaction_month and len(periods) != 1:
        return {'available': False, 'status': 'PERIOD_UNRESOLVED', 'message': 'Rural CSP source period could not be aligned to a single uploaded transaction month.', 'rows': [], 'summary': {}}
    period = transaction_month or next(iter(periods))

    cm = commission.copy()
    cm['csp_id'] = cm['csp_id'].map(norm)
    cm['transaction_type'] = cm['transaction_type'].map(norm)
    cm['report_base'] = pd.to_numeric(cm.get('report_base'), errors='coerce')
    cm['actual_commission'] = pd.to_numeric(cm.get('actual_commission'), errors='coerce')
    mapping = mapping.copy()
    mapping['transaction_type'] = mapping['transaction_type'].map(norm)
    mapping['count_as_txn'] = mapping['count_as_txn'].map(norm)
    txn_types = set(mapping.loc[mapping['count_as_txn'].eq('Y'), 'transaction_type'])
    pmjdy_types = {x for x in txn_types if x.startswith('ACC OPEN WITH EKYC AND INIT DEP ')}
    bank = cm[cm['csp_id'].ne('')].copy()
    bank['count_value'] = bank['report_base'].fillna(0)
    txn = bank[bank['transaction_type'].isin(txn_types)].groupby('csp_id', as_index=True)['count_value'].sum()
    pmjdy = bank[bank['transaction_type'].isin(pmjdy_types)].groupby('csp_id', as_index=True)['count_value'].sum()
    rural_paid = bank[bank['transaction_type'].eq('RURAL COMMISSION')].groupby('csp_id', as_index=True)['actual_commission'].sum()
    area = _bank_area_by_csp(cm)

    rows=[]
    for _, m in master.iterrows():
        csp=m['csp_id']; login=m['login_days']
        t=float(txn.get(csp,0) or 0); p=float(pmjdy.get(csp,0) or 0); paid=float(rural_paid.get(csp,0) or 0)
        cond1 = bool(pd.notna(login) and float(login) >= RURAL_MIN_LOGIN_DAYS)
        cond2_pmjdy = bool(p >= RURAL_MIN_PMJDY)
        cond2_txn = bool(t >= RURAL_MIN_TXN)
        cond2 = bool(cond2_pmjdy or cond2_txn)
        bank_area = area.get(csp)
        area_conflict = bank_area == 'CONFLICT'
        area_not_applicable = bank_area in RURAL_NOT_APPLICABLE_AREAS
        eligibility_assessed = (not area_conflict) and (area_not_applicable or not pd.isna(login))
        eligible = bool(cond1 and cond2 and not area_not_applicable and not area_conflict)
        # Do not publish a guessed expected amount when geography conflicts or login-day
        # evidence is missing. Urban/Metro is explicitly not applicable, so expected is 0.
        expected = float('nan') if (area_conflict or (pd.isna(login) and not area_not_applicable)) else (RURAL_INCENTIVE_AMOUNT if eligible else 0.0)
        status='Matched'
        note=''
        if area_conflict:
            status='Bank area conflict - verify'
            note='Current BC source has conflicting geography for this CSP; expected Rural Commission is unresolved until the source is corrected.'
        elif area_not_applicable:
            status='Not applicable - Urban/Metro'
            note='SBI Rural CSP incentive is not applicable to Urban/Metro CSPs.'
        elif pd.isna(login):
            status='Login days missing - verify'; note='Eligibility cannot be assessed without current-period login days.'
        elif paid > 0 and not eligible:
            status='Excess paid by bank (not eligible)'
            note='Bank paid Rural Commission although SBI Rural Commission Rule eligibility test is not satisfied; no pro-rata rule is assumed.'
        elif eligible and paid <= 0:
            status='Short paid by bank'
            note='Eligible as per supplied rule but no Rural Commission is present in the BC actual source.'
        elif eligible and abs(paid-expected) > 0.005:
            status='Short paid by bank' if paid < expected else 'Excess paid by bank'
            note='Paid amount differs from fixed ₹2,000 incentive.'
        rows.append({
            'csp_id':csp,'csp_name':m.get('csp_name',''),'csp_category':m.get('csp_category',''),
            'relationship_manager':m.get('relationship_manager',''),'area_bank':bank_area or None,
            'period':period,'login_days':login,'txn_count':t,'pmjdy_count':p,
            'login_eligible':cond1,'pmjdy_eligible':cond2_pmjdy, 'txn_eligible':cond2_txn, 'txn_or_pmjdy_eligible':cond2,'eligibility_assessed':eligibility_assessed,'urban_metro_not_applicable':area_not_applicable,'eligible':eligible,
            'expected_commission':expected,'actual_commission':paid,
            'difference_bank_minus_expected':paid-expected,'status':status,'note':note,
        })
    r=pd.DataFrame(rows)
    paid_unmapped = rural_paid[~rural_paid.index.isin(set(master['csp_id']))]
    summary={
        'period':period,'rural_csp_count':int(len(master)),'login_ge_20':int(r['login_eligible'].sum()),
        'eligible_csp_count':int(r['eligible'].sum()),'expected_commission':float(r['expected_commission'].sum(min_count=1)) if r['expected_commission'].notna().any() else None,
        'bank_paid_to_eligible':float(r.loc[r['eligible'],'actual_commission'].sum()),
        'short_paid_csp_count':int(((r['eligible']) & (r['actual_commission'] < r['expected_commission'] - .005)).sum()),
        'short_paid_amount':float((r.loc[r['eligible'],'expected_commission']-r.loc[r['eligible'],'actual_commission']).clip(lower=0).sum()),
        'excess_csp_count':int(((~r['eligible']) & (r['actual_commission'] > 0)).sum()),
        'excess_paid_amount':float(r.loc[~r['eligible'],'actual_commission'].sum()),
        'login_missing_count':int(r['login_days'].isna().sum()),
        'urban_metro_not_applicable_count':int(r['urban_metro_not_applicable'].sum()),
        'geography_unresolved_count':int(r['status'].eq('Bank area conflict - verify').sum()),
        'eligibility_unresolved_count':int((~r['eligibility_assessed']).sum()),
        'unmapped_paid_csp_count':int(len(paid_unmapped)),
        'unmapped_paid_amount':float(paid_unmapped.sum()) if len(paid_unmapped) else 0.0,
        'total_bank_rural_commission':float(rural_paid.sum()),
        'mapping_transaction_types':int(len(mapping)),
        'mapping_count_as_txn_types':int(len(txn_types)),
        'pmjdy_transaction_types':sorted(pmjdy_types),
        'source_basis':'Current-period Rural CSP login-day file + current BC commission report + approved TXN Types mapping',
         'rule_code':RURAL_RULE_CODE,
         'rule_name':RURAL_RULE_NAME,
         'rule_text':'Condition 1: ID must be Logged-In minimum 20 Days; Condition 2: minimum 50 PMJDY OR minimum 100 approved TXN per month (either or both); Incentive ₹2,000; Urban/Metro Not Applicable.',
         'eligibility_logic':'Rural/Semi-Urban AND login_days >= 20 AND (pmjdy_count >= 50 OR approved_txn_count >= 100); Urban/Metro = Not Applicable',
         'incentive_amount':RURAL_INCENTIVE_AMOUNT,
         'minimum_login_days':RURAL_MIN_LOGIN_DAYS,
         'minimum_pmjdy':RURAL_MIN_PMJDY,
         'minimum_txn':RURAL_MIN_TXN,
    }
    # The actual total can include CSPs not present in the Rural master; keep the control explicit.
    summary['reconciled_bank_total'] = summary['bank_paid_to_eligible'] + summary['excess_paid_amount'] + summary['unmapped_paid_amount']
    return {'available':True,'status':'READY','message':'Rural Commission control calculated for the current uploaded period.','summary':summary,'rows':r.to_dict(orient='records'),'unmapped_paid': [{'csp_id':str(k),'actual_commission':float(v)} for k,v in paid_unmapped.items()]}
