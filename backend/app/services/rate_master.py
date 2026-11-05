"""Approved commercial-rule parser and deterministic expected-commission engine."""
from functools import lru_cache
import re
import warnings as _warnings
import numpy as np
import pandas as pd
from app.services import excel_io
from decimal import Decimal, ROUND_HALF_UP
from .number_parser import parse_numeric_series, map_unique
from .fast_text import on_unique

RATE_ALIASES={
 'rule_id':['rule_id','rule','rule_code','rate_id','id'],
 'transaction_type':['transaction_type','txn_type','commission_type','service_type','product','product_name','product_service','product_or_service','component','component_name','product_type','service','service_name','type_of_transaction'],
 'effective_from':['effective_from','valid_from','start_date','from_date','effective_date','effective_start','validity_from'],
 'effective_to':['effective_to','valid_to','end_date','to_date','effective_end','validity_to'],
 'min_amount':['min_amount','minimum_amount','slab_min','from_amount','amount_from','min_txn_amount','slab_from','from'],
 'max_amount':['max_amount','maximum_amount','slab_max','to_amount','amount_to','max_txn_amount','slab_to','to'],
 'rate_type':['rate_type','calculation_type','basis','commission_type','calculation_basis'],
 'rate':['rate','commission_rate','percentage','percent','rate_value','commission','commission_amount','commission_value','commission_rs','commission_inr','commission_rupees','commission_per_transaction','commission_per_txn','commission_per_enrollment','payout','payout_rate','fee','fee_amount','remuneration','incentive','avg_per_enrollment_revenue','avg_revenue_per_enrollment'],
 'fixed_fee':['fixed_fee','fixed_commission','flat_fee','fixed_amount'],
 'cap':['cap','max_commission','commission_cap'],
 'floor':['floor','min_commission','commission_floor'],
 'csp_id':['csp_id','csp','csp_code','csp_code_new','agent_id','bc_id'],
 'channel':['channel','channel_type'],
 'priority':['priority','rule_priority'],
 'sub_category':['sub_category','sub_category_rule','subcategory','rule_description'],
 'enrollment_type':['enrollment_type','rule_type','category_type'],
 'commission_cycle':['commission_cycle','cycle','frequency']}

@lru_cache(maxsize=65536)
def _norm_text(v):
    return ' '.join(v.strip().upper().split())

def norm(v):
    # Called once per row on large uploads; string results are cached (same output as before).
    if type(v) is str: return _norm_text(v)
    if pd.isna(v): return ''
    return ' '.join(str(v).strip().upper().split())

def _parse_dates(series):
    if pd.api.types.is_datetime64_dtype(series):
        # Already parsed (the transaction frame arrives with real datetimes): rendering them to text and parsing that
        # text again returns the same instants, so skip the round trip.
        return series.astype('datetime64[ns]').rename(None)
    raw=series.astype('string').str.strip(); iso=raw.str.match(r'^\d{4}-\d{2}-\d{2}',na=False)
    out=pd.Series(pd.NaT,index=series.index,dtype='datetime64[ns]')
    if iso.any(): out.loc[iso]=pd.to_datetime(raw.loc[iso],errors='coerce')
    if (~iso).any(): out.loc[~iso]=pd.to_datetime(raw.loc[~iso],errors='coerce',dayfirst=True,format='mixed')
    return out

def _parse_slab_text(series):
    raw=series.astype('string').fillna('').str.strip()
    s=raw.str.upper()
    low=pd.to_numeric(s.str.extract(r'(?:>=|>|FROM\s*)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:-|TO|–|—)')[0].str.replace(',','',regex=False),errors='coerce')
    high=pd.to_numeric(s.str.extract(r'(?:-|TO|–|—)\s*([0-9][0-9,]*(?:\.[0-9]+)?)')[0].str.replace(',','',regex=False),errors='coerce')
    plus=pd.to_numeric(s.str.extract(r'([0-9][0-9,]*(?:\.[0-9]+)?)\s*\+')[0].str.replace(',','',regex=False),errors='coerce')
    # Specific business wording used by the Eko/SBI product master.
    m1=s.str.extract(r'(?:INITIAL\s+DEPOSIT|DEPOSIT).*?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:AND|TO)\s*<\s*([0-9][0-9,]*(?:\.[0-9]+)?)')
    m2=s.str.extract(r'(?:INITIAL\s+DEPOSIT|DEPOSIT).*?([0-9][0-9,]*(?:\.[0-9]+)?)\s*\+?\s*$')
    low=low.fillna(pd.to_numeric(m1[0].str.replace(',','',regex=False),errors='coerce'))
    high=high.fillna(pd.to_numeric(m1[1].str.replace(',','',regex=False),errors='coerce'))
    high=high.fillna(plus)
    # Inclusive/exclusive wording is handled with epsilon-free transaction tests below.
    return low,high

def _month_rule(text):
    s=norm(text)
    q={
      'Q1':{6,7,8},'Q2':{9,10,11},'Q3':{12,1,2},'Q4':{3,4,5}}
    for k,months in q.items():
        if re.search(rf'\b{k}\b',s): return ','.join(map(str,sorted(months)))
    return ''

def _parse_rate_value(series):
    raw=series.astype('string').fillna('').str.strip()
    cleaned=raw.str.replace(',', '', regex=False)
    pct=cleaned.str.extract(r'([0-9]+(?:\.[0-9]+)?)\s*%')[0]
    numeric=parse_numeric_series(cleaned.str.extract(r'^\s*([0-9]+(?:\.[0-9]+)?)\s*$')[0])
    parsed=numeric.astype('Float64').combine_first(pd.to_numeric(pct,errors='coerce').astype('Float64'))
    return parsed,pct.notna()

def standardize_rate_master(df):
    result=df.copy(); result.columns=(result.columns.astype(str).str.strip().str.lower().str.replace(r'[^a-z0-9]+','_',regex=True).str.strip('_'))
    mapping={}
    for standard,cands in RATE_ALIASES.items():
        for c in cands:
            if c in result.columns: mapping[c]=standard; break
    result=result.rename(columns=mapping)
    if 'transaction_type' in result.columns:
        result['transaction_type']=result['transaction_type'].astype('string').str.strip().replace('',pd.NA).ffill()
    result=result.dropna(how='all').reset_index(drop=True)
    return result,mapping

def validate_rate_master(df):
    df,m=standardize_rate_master(df)
    missing=[]
    if 'transaction_type' not in df.columns: missing.append('transaction_type/product/component')
    if 'rate' not in df.columns: missing.append('rate/commission/avg per enrollment revenue')
    if missing:
        return df,{'valid':False,'missing_columns':missing,'mapped_columns':m,'rows':len(df),'errors':['Could not map the uploaded product-wise commission master to the required commercial fields.']}
    out=df.copy(); out['transaction_type']=map_unique(out['transaction_type'], norm); out=out[out['transaction_type'].ne('')].copy()
    if 'sub_category' not in out.columns: out['sub_category']=''
    out['sub_category']=out['sub_category'].fillna('').astype(str).str.strip()
    out['rate'],percent_mask=_parse_rate_value(out['rate'])
    if 'rate_type' not in out.columns:
        out['rate_type']='FIXED'; out.loc[percent_mask,'rate_type']='PERCENTAGE'; inferred=True
    else:
        out['rate_type']=map_unique(out['rate_type'], norm); out.loc[percent_mask & out['rate_type'].isin({'','FIXED','FLAT'}),'rate_type']='PERCENTAGE'; inferred=False
    low,high=_parse_slab_text(out['sub_category'])
    txt=out['sub_category'].fillna('').astype(str).str.upper()
    # Explicitly parse the account-opening slabs used by the approved product master.
    acct=out['transaction_type'].eq('ACCOUNT OPPENING (PMJDY)')
    low=low.astype('Float64'); high=high.astype('Float64')
    low.loc[acct & txt.str.contains(r'INITIAL DEPOSIT\s*<\s*RS\.?\s*100',regex=True,na=False)] = pd.NA
    high.loc[acct & txt.str.contains(r'INITIAL DEPOSIT\s*<\s*RS\.?\s*100',regex=True,na=False)] = 100
    low.loc[acct & txt.str.contains(r'[>=≥]\s*RS\.?\s*1000',regex=True,na=False)] = 1000
    high.loc[acct & txt.str.contains(r'[>=≥]\s*RS\.?\s*500\s+TO\s*<\s*RS\.?\s*1000',regex=True,na=False)] = 1000
    low.loc[acct & txt.str.contains(r'[>=≥]\s*RS\.?\s*500\s+TO',regex=True,na=False)] = 500
    high.loc[acct & txt.str.contains(r'[>=≥]\s*RS\.?\s*100\s+TO\s*<\s*RS\.?\s*500',regex=True,na=False)] = 500
    low.loc[acct & txt.str.contains(r'[>=≥]\s*RS\.?\s*100\s+TO',regex=True,na=False)] = 100
    out['max_exclusive']=txt.str.contains(r'<|BELOW|BTWN', regex=True, na=False)
    if 'min_amount' not in out.columns: out['min_amount']=low
    else: out['min_amount']=pd.to_numeric(out['min_amount'],errors='coerce').fillna(low)
    if 'max_amount' not in out.columns: out['max_amount']=high
    else: out['max_amount']=pd.to_numeric(out['max_amount'],errors='coerce').fillna(high)
    for c in ['rate','fixed_fee','min_amount','max_amount','cap','floor','priority']:
        if c in out: out[c]=parse_numeric_series(out[c])
    for c in ['effective_from','effective_to']:
        if c in out: out[c]=_parse_dates(out[c])
    if 'csp_id' in out: out['csp_id']=map_unique(out['csp_id'], norm)
    if 'channel' in out: out['channel']=map_unique(out['channel'], norm)
    if 'enrollment_type' in out: out['enrollment_type']=out['enrollment_type'].fillna('').astype(str).str.strip()
    if 'commission_cycle' in out: out['commission_cycle']=out['commission_cycle'].fillna('').astype(str).str.strip()
    out['allowed_months']=out['sub_category'].map(_month_rule)
    # Preserve an explicit approved scope from normalized CSV masters. Workbook
    # imports derive it from enrollment_type, but reference CSVs often expose only
    # commercial_scope; defaulting a missing enrollment_type to a string used to
    # raise AttributeError and, if papered over, could mark every rule non-transactional.
    enrollment_scope = map_unique(out['enrollment_type'], norm) if 'enrollment_type' in out.columns else pd.Series('', index=out.index, dtype='object')
    enrollment_scope = enrollment_scope.replace({'COMMISSION':'TRANSACTION','TRANSACTIONAL':'TRANSACTION'})
    if 'commercial_scope' in out.columns:
        explicit_scope = map_unique(out['commercial_scope'], norm).replace({'COMMISSION':'TRANSACTION','TRANSACTIONAL':'TRANSACTION','NONTRANSACTION':'NON_TRANSACTION'})
        out['commercial_scope'] = explicit_scope.where(explicit_scope.isin({'TRANSACTION','NON_TRANSACTION'}), enrollment_scope)
    else:
        out['commercial_scope'] = enrollment_scope
    out['commercial_scope'] = out['commercial_scope'].where(out['commercial_scope'].isin({'TRANSACTION'}),'NON_TRANSACTION')
    out['rule_id']=out.get('rule_id',pd.Series(index=out.index,dtype='object')).fillna('').astype(str)
    out.loc[out['rule_id'].eq(''),'rule_id']='RM-' + out.index.astype(str)
    errors=[]; warnings=[]
    allowed={'FIXED','FLAT','RATE','PERCENTAGE','PERCENT','PERCENTAGE_PLUS_FIXED','FIXED_PLUS_PERCENTAGE','FEE_PERCENTAGE'}
    sig_cols=['transaction_type','csp_id','channel','kyc_requirement','sub_category','rate_type','rate','fixed_fee','min_amount','max_amount','effective_from','effective_to','priority','allowed_months','max_exclusive','basis']
    sig_cols=[c for c in sig_cols if c in out.columns]
    if sig_cols and int(out.duplicated(subset=sig_cols,keep=False).sum())>0:
        errors.append(f"Duplicate commercial rule rows detected: {int(out.duplicated(subset=sig_cols,keep=False).sum())} row(s) have identical rule dimensions and values.")
    bad=~out['rate_type'].isin(allowed); bad=bad & out['rate'].notna()
    if bad.any(): errors.append('Unsupported rate_type found: '+', '.join(sorted(out.loc[bad,'rate_type'].dropna().unique().tolist())))
    if out['rate'].isna().any(): warnings.append(f"{int(out['rate'].isna().sum())} rule row(s) have no numeric commission value and are retained as non-transactional/unrated exceptions; they are never treated as zero.")
    if out['min_amount'].notna().any() and out['max_amount'].notna().any():
        badrange=out['min_amount'].notna()&out['max_amount'].notna()&(out['min_amount']>out['max_amount'])
        if badrange.any(): errors.append('min_amount is greater than max_amount in one or more rules.')
    if percent_mask.any(): warnings.append('Percentage values detected. "0.50% + GST" is calculated as 0.50% commission; GST is not added to revenue unless an explicit approved GST rule is provided.')
    if inferred: warnings.append('Rate Type was not supplied; numeric values are treated as fixed per eligible transaction and percentage-formatted values as percentage rates.')
    if 'priority' not in out: out['priority']=0
    out['priority']=out['priority'].fillna(0)
    # Detect overlapping amount slabs at equal priority for the same commercial
    # dimensions. Keep the workbook uploadable, but make ambiguity visible before
    # transaction processing; runtime still refuses to pick an arbitrary rate.
    dimension_cols=[c for c in ['transaction_type','csp_id','channel','kyc_requirement','priority','effective_from','effective_to'] if c in out.columns]
    overlap_messages=[]
    for _, group in out.groupby(dimension_cols, dropna=False, sort=False):
        rows=list(group.iterrows())
        if len(rows)<2: continue
        for pos_a in range(len(rows)):
            ia,a=rows[pos_a]
            amin=float(a['min_amount']) if pd.notna(a.get('min_amount')) else float('-inf')
            amax=float(a['max_amount']) if pd.notna(a.get('max_amount')) else float('inf')
            if bool(a.get('min_exclusive',False)): amin=np.nextafter(amin,float('inf'))
            if bool(a.get('max_exclusive',False)): amax=np.nextafter(amax,float('-inf'))
            for pos_b in range(pos_a+1,len(rows)):
                ib,b=rows[pos_b]
                bmin=float(b['min_amount']) if pd.notna(b.get('min_amount')) else float('-inf')
                bmax=float(b['max_amount']) if pd.notna(b.get('max_amount')) else float('inf')
                if bool(b.get('min_exclusive',False)): bmin=np.nextafter(bmin,float('inf'))
                if bool(b.get('max_exclusive',False)): bmax=np.nextafter(bmax,float('-inf'))
                if max(amin,bmin)<=min(amax,bmax):
                    label=str(a.get('transaction_type','UNKNOWN'))
                    message=f"Overlapping amount slabs for {label}: {a.get('rule_id','')} and {b.get('rule_id','')}; affected transactions may require product/eligibility evidence."
                    if message not in overlap_messages: overlap_messages.append(message)
    if overlap_messages:
        warnings.extend(overlap_messages)
    return out,{'valid':len(out)>0 and not errors,'missing_columns':missing,'mapped_columns':m,'rows':len(out),'errors':errors,'warnings':warnings,'transaction_types':int(out['transaction_type'].nunique()),'rules':len(out),'transaction_rules':int((out['commercial_scope']=='TRANSACTION').sum()),'overlapping_slab_pairs':len(overlap_messages)}

def _money(x):
    if pd.isna(x): return Decimal('0')
    return Decimal(str(x))

def _calculate_value(amount,rate,rate_type,fixed,cap,floor):
    a=_money(amount); r=_money(rate); f=_money(fixed); typ=norm(rate_type)
    if typ in {'PERCENTAGE','PERCENT'}: v=a*r/Decimal('100')
    elif typ in {'PERCENTAGE_PLUS_FIXED','FIXED_PLUS_PERCENTAGE'}: v=a*r/Decimal('100')+f
    else: v=r+f
    if pd.notna(floor): v=max(v,_money(floor))
    if pd.notna(cap): v=min(v,_money(cap))
    return float(v.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))

def _normalize_kyc(value):
    """Normalize explicit KYC evidence without guessing missing/ambiguous values."""
    s=norm(value)
    if not s: return ''
    if s in {"E-KYC","EKYC","E KYC","WITH E-KYC","WITH EKYC","WITH E KYC","E KYC DONE","EKYC DONE"}: return "EKYC"
    if s in {"WITHOUT E-KYC","WITHOUT EKYC","WITHOUT E KYC","OVD","WITH OVD","WITHOUT E-KYC (OVD)","WITHOUT EKYC (OVD)","OFFLINE OVD"}: return "OVD"
    return s



def apply_confirmed_remittance_reference_rules(rules, id_pattern=r'^CM0(18|21)-'):
    """Overlay only the 16 screenshot-confirmed CM018/CM021 remittance slabs.

    The supplied SBI screenshot explicitly defines Home-branch Remittance Transfer
    (CM018) and Non-home-branch Remittance Cash (CM021). The generic workbook parser
    can otherwise downgrade these exact rules to MAPPING TO CONFIRM on startup or
    re-upload. The permanent reference CSV is the controlled source for these rows.
    No transaction or monthly data is read here.
    """
    from pathlib import Path
    import pandas as pd
    if rules is None:
        return rules
    out=rules.copy().astype(object)
    ref_path=Path(__file__).resolve().parents[1] / 'data' / 'rate_master' / 'approved_rule_master_reference.csv'
    if not ref_path.exists():
        return out
    try:
        ref=pd.read_csv(ref_path,dtype=str,keep_default_na=False)
        ids=ref['rule_id'].astype(str).str.match(id_pattern)
        ref=ref.loc[ids].copy()
        if ref.empty:
            return out
        if 'rule_id' not in out.columns:
            out['rule_id']=''
        out['rule_id']=out['rule_id'].astype(str)
        for _, row in ref.iterrows():
            rid=str(row['rule_id'])
            mask=out['rule_id'].eq(rid)
            if mask.any():
                for col in ref.columns:
                    if col not in out.columns:
                        out[col]=''
                    out.loc[mask,col]=row[col]
            else:
                for col in ref.columns:
                    if col not in out.columns:
                        out[col]=''
                missing={col:'' for col in out.columns}
                for col in ref.columns:
                    missing[col]=row[col]
                out=pd.concat([out,pd.DataFrame([missing])],ignore_index=True)
        return out.reset_index(drop=True)
    except Exception:
        # Never fail an upload because a reference override could not be applied;
        # tests assert the required approved rows exist in the release reference.
        return out


def apply_sbi_pdf_schedule_rules(rules):
    """Apply the SBI "Updated Commission Structure (01.04.2025)" PDF to products that have no line of their own in it.

    The PDF has schedules for Cash Withdrawal (4), Cash Deposit (5), Remittance Cash non-home (6.a), Remittance Transfer
    home (6.b) and "Deposit in loan accounts - un-mapped: as per cash deposit" (18); it has no line for AEPS ONUS, AEPS
    acquirer, debit-card, mATM/ATM or YONO transactions, which are cash withdrawals, deposits or transfers. For September
    and August 2026 the bank's payments follow these schedules (AEPS ONUS / acquirer / debit-card off-us withdrawals: 88-100%
    of agents within 2%, totals within 0.3%).
    * the CM010/012/013/019/020/051 reference rows (generic schedules) become CONFIRMED;
    * AEPS ACQUIRER WITHDRAWAL, DEBIT CARD ONUS/OFFUS and YONO CASH use the Cash Withdrawal schedule; the workbook's Rs 1
      acquirer and Rs 15 YONO rates (from the Excel, not in the PDF) are removed.
    """
    out=apply_confirmed_remittance_reference_rules(rules, id_pattern=r'^CM0(10|12|13|19|20|51)(-|$)')
    out=out.copy().astype(object)
    ids=out['rule_id'].astype(str)
    generic=ids.str.match(r'^CM0(10|12|13|19|20|51)(-|$)')
    out.loc[generic,'rule_status']='CONFIRMED'
    out=out[~ids.isin(['RM-EC-17','RM-EC-18']) & ~ids.str.startswith('PDF4-')].copy()
    base=out[out['rule_id'].astype(str).str.match(r'^RM-EC-(9|10|11|12)-(RURAL|URBAN)$')]
    copies=[]
    for target,code in (('AEPS ACQUIRER WITHDRAWAL','AEPSACQ'),('DEBIT CARD ONUS','DCON'),('DEBIT CARD OFFUS','DCOFF'),('YONO CASH','YONO')):
        for _,row in base.iterrows():
            r=row.copy(); r['transaction_type']=target; r['rule_id']='PDF4-%s-%s'%(code,str(row['rule_id'])[len('RM-EC-'):])
            r['rule_status']='CONFIRMED'; r['sub_category']='Cash Withdrawal schedule (SBI PDF item 4) applied to '+target
            copies.append(r)
    if copies:
        out=pd.concat([out,pd.DataFrame(copies)],ignore_index=True)
    return out.reset_index(drop=True)

def _close_integer_slab_gaps(r):
    """SBI slabs are written in whole rupees: "Up to Rs. 10,000" then "Rs. 10,001 to Rs. 15,000".
    An amount with paise such as 10,000.50 belongs to the higher slab, but a literal ">= 10,001"
    leaves it unmatched (no commission). When a slab starts exactly 1 rupee after another slab of the
    same product/channel/CSP/KYC/months ends, start it "above" the previous maximum instead (V62.6.210).
    """
    if r.empty or 'min_amount' not in r or 'max_amount' not in r:
        return r
    r=r.copy()
    if 'min_exclusive' not in r: r['min_exclusive']=False
    if 'max_exclusive' not in r: r['max_exclusive']=False
    flag=lambda v: str(v).strip().lower() in {'true','1','yes'}
    r['min_exclusive']=r['min_exclusive'].map(flag); r['max_exclusive']=r['max_exclusive'].map(flag)
    keys=[c for c in ('transaction_type','channel','csp_id','kyc_requirement','allowed_months') if c in r]
    key=r[keys].astype(str).agg('|'.join,axis=1) if keys else pd.Series('',index=r.index)
    for _,grp in r.groupby(key,sort=False):
        ends={float(m) for m,x in zip(grp['max_amount'],grp['max_exclusive']) if pd.notna(m) and not x}
        for i in grp.index:
            mn=r.at[i,'min_amount']
            if pd.notna(mn) and not r.at[i,'min_exclusive'] and float(mn)-1 in ends and float(mn)==int(float(mn)):
                r.at[i,'min_amount']=float(mn)-1; r.at[i,'min_exclusive']=True
    return r

def calculate_expected(transactions,rules, _allow_geo_scenario=False):
    """Fast deterministic SBI rule matcher.

    Rules are matched by transaction type first, then by CSP/geography/date/amount
    conditions. A transaction is calculated only when exactly one highest-priority
    rule matches. Geography is never guessed; optional scenario evaluation is off by
    default and is retained only for controlled internal use.
    """
    tx=transactions.copy()
    # Preserve explicit product/KYC wording before canonicalizing aliases.  KYC
    # is inferred only when the source label explicitly states e-KYC or OVD.
    raw_rule_type=map_unique(tx['rule_type'], norm)
    if 'kyc_type' not in tx.columns:
        tx['kyc_type']=''
    tx['kyc_type']=tx['kyc_type'].fillna('').astype(str)
    kyc_blank=on_unique(tx['kyc_type'], lambda x: x.str.strip()).eq('')
    explicit_ovd=on_unique(raw_rule_type, lambda x: x.str.contains(r'WITHOUT\s+E[- ]?KYC|WITH\s+OVD|OFFICIALLY VALID DOCUMENT',regex=True,na=False))
    explicit_ekyc=on_unique(raw_rule_type, lambda x: x.str.contains(r'WITH\s+E[- ]?KYC',regex=True,na=False)) & ~explicit_ovd
    tx.loc[kyc_blank & explicit_ovd,'kyc_type']='OVD'
    tx.loc[kyc_blank & explicit_ekyc,'kyc_type']='EKYC'
    tx['rule_type']=map_unique(raw_rule_type, _canonical_commercial_type)
    tx['csp_id']=map_unique(tx['csp_id'], norm)
    if 'channel' not in tx.columns:
        for candidate in ['population','location_type','area_type','csp_category','csp_location']:
            if candidate in tx.columns:
                tx['channel']=tx[candidate]; break
    if 'channel' in tx.columns:
        tx['channel']=map_unique(tx['channel'], norm).replace({'SEMI URBAN':'RURAL','SEMI-URBAN':'RURAL','SEMIURBAN':'RURAL','URBAN/METRO':'URBAN','METRO':'URBAN'})
    else: tx['channel']=''
    if 'kyc_type' in tx.columns:
        tx['kyc_type']=map_unique(tx['kyc_type'], _normalize_kyc)
    else: tx['kyc_type']=''
    tx['amount']=parse_numeric_series(tx['amount'])
    tx['transaction_date']=_parse_dates(tx['transaction_date']) if 'transaction_date' in tx else pd.Series(pd.NaT,index=tx.index)

    r=rules.copy().reset_index(drop=True)
    scope=r.get('commercial_scope',pd.Series('TRANSACTION',index=r.index)).astype('string').fillna('').map(norm)
    r=r[(r['rate'].notna()) & scope.eq('TRANSACTION')].copy().reset_index(drop=True)
    if r.empty:
        out=tx.copy(); out['expected_commission']=np.nan; out['commission_rule_id']=pd.NA; out['rate_status']='Rate Master Missing'; out['rule_exists']=False; out['condition_failure']=False; out['required_evidence_missing']=False; out['condition_fail_reason']='No executable rule exists in the rate master'
        return out,{'missing_rules':len(out),'ambiguous_rules':0,'applied_rules':0,'pending_mapping_rules':0,'transaction_rules':0}
    tx['rule_exists']=tx['rule_type'].isin(set(r['transaction_type'].astype(str)))
    tx['condition_failure']=False
    tx['required_evidence_missing']=False
    tx['condition_fail_reason']=''
    r['transaction_type']=map_unique(r['transaction_type'], norm)
    r['csp_id']=map_unique(r['csp_id'], norm) if 'csp_id' in r else ''
    r['channel']=map_unique(r['channel'], norm) if 'channel' in r else ''
    r['kyc_requirement']=r['kyc_requirement'].map(_normalize_kyc) if 'kyc_requirement' in r else ''
    r['effective_from']=_parse_dates(r['effective_from']) if 'effective_from' in r else pd.Series(pd.NaT,index=r.index)
    r['effective_to']=_parse_dates(r['effective_to']) if 'effective_to' in r else pd.Series(pd.NaT,index=r.index)
    r['rate_type']=map_unique(r['rate_type'], norm) if 'rate_type' in r else 'FIXED'
    for c in ['min_amount','max_amount','rate','fixed_fee','cap','floor','priority']:
        if c not in r: r[c]=pd.NA
        r[c]=parse_numeric_series(r[c])
    r['priority']=r['priority'].fillna(0)
    r=_close_integer_slab_gaps(r)
    if 'rule_id' not in r: r['rule_id']='RM-'+r.index.astype(str)
    r['rule_id']=r['rule_id'].fillna('').astype(str)

    n=len(tx); best_priority=np.full(n,-np.inf); best_count=np.zeros(n,dtype=np.int16); best_rule=np.full(n,-1,dtype=np.int32)
    type_arr=tx['rule_type'].astype(str).to_numpy(); csp_arr=tx['csp_id'].astype(str).to_numpy(); ch_arr=tx['channel'].astype(str).to_numpy(); kyc_arr=tx['kyc_type'].astype(str).to_numpy()
    amt_arr=pd.to_numeric(tx['amount'],errors='coerce').to_numpy(dtype=float); date_arr=tx['transaction_date'].to_numpy(dtype='datetime64[ns]')
    grouped=r.groupby('transaction_type',sort=False).groups
    for rule_type, ridxs in grouped.items():
        idx=np.flatnonzero(type_arr==rule_type)
        if idx.size==0: continue
        sub_amt=amt_arr[idx]; sub_csp=csp_arr[idx]; sub_ch=ch_arr[idx]; sub_kyc=kyc_arr[idx]; sub_date=date_arr[idx]
        bp=best_priority[idx]; bc=best_count[idx]; br=best_rule[idx]
        for ri in ridxs:
            rr=r.loc[ri]; mask=np.ones(idx.size,dtype=bool)
            rc=str(rr.get('csp_id','') or '')
            if rc: mask &= sub_csp==rc
            rch=str(rr.get('channel','') or '')
            if rch: mask &= sub_ch==rch
            rk=str(rr.get('kyc_requirement','') or '')
            if rk: mask &= sub_kyc==rk
            ef=rr.get('effective_from'); et=rr.get('effective_to')
            if pd.notna(ef): mask &= ~pd.isna(sub_date) & (sub_date>=np.datetime64(ef))
            if pd.notna(et): mask &= ~pd.isna(sub_date) & (sub_date<=np.datetime64(et))
            mn=rr.get('min_amount'); mx=rr.get('max_amount')
            if pd.notna(mn): mask &= np.isfinite(sub_amt) & (sub_amt > float(mn) if bool(rr.get('min_exclusive',False)) else sub_amt>=float(mn))
            if pd.notna(mx): mask &= np.isfinite(sub_amt) & (sub_amt < float(mx) if bool(rr.get('max_exclusive',False)) else sub_amt<=float(mx))
            allowed=rr.get('allowed_months','')
            if pd.notna(allowed) and str(allowed).strip():
                months={int(x) for x in str(allowed).split(',') if str(x).strip().isdigit()}
                valid_dates=~pd.isna(sub_date)
                monthvals=pd.Series(sub_date).dt.month.to_numpy()
                mask &= valid_dates & np.isin(monthvals,list(months))
            if not mask.any(): continue
            p=float(rr.get('priority',0) or 0)
            higher=mask & (p>bp); equal=mask & (p==bp)
            if higher.any():
                bp[higher]=p; bc[higher]=1; br[higher]=int(ri)
            eq_only=equal & ~higher
            if eq_only.any(): bc[eq_only]+=1
        best_priority[idx]=bp; best_count[idx]=bc; best_rule[idx]=br

    applied=(best_rule>=0)&(best_count==1); ambiguous=best_count>1; missing=best_rule<0
    expected=np.full(n,np.nan); rule_ids=np.full(n,None,dtype=object)
    if applied.any():
        pos=np.flatnonzero(applied); ridx=best_rule[pos]; sub=r.iloc[ridx]
        a=amt_arr[pos]; rate=pd.to_numeric(sub['rate'],errors='coerce').fillna(0).to_numpy(dtype=float)
        fixed=pd.to_numeric(sub.get('fixed_fee',pd.Series(0,index=sub.index)),errors='coerce').fillna(0).to_numpy(dtype=float)
        typ=sub['rate_type'].astype(str).str.upper().to_numpy(); vals=np.where(np.isin(typ,['PERCENTAGE','PERCENT']),a*rate/100.0,rate+fixed)
        plus=np.isin(typ,['PERCENTAGE_PLUS_FIXED','FIXED_PLUS_PERCENTAGE']); vals=np.where(plus,a*rate/100.0+fixed,vals)
        fee_types=typ=='FEE_PERCENTAGE'
        if fee_types.any():
            fee_rate=np.zeros(len(sub)); fee_floor=np.full(len(sub),np.nan); fee_cap=np.full(len(sub),np.nan); comm_floor=np.full(len(sub),np.nan); comm_cap=np.full(len(sub),np.nan)
            for j,b in enumerate(sub.get('basis',pd.Series('',index=sub.index)).astype(str)):
                for part in b.split(';'):
                    if '=' not in part: continue
                    k,v=part.split('=',1)
                    try:
                        z=float(v)
                    except Exception: continue
                    if k=='fee_rate': fee_rate[j]=z
                    elif k=='fee_min': fee_floor[j]=z
                    elif k=='fee_max': fee_cap[j]=z
                    elif k=='commission_min': comm_floor[j]=z
                    elif k=='commission_max': comm_cap[j]=z
            fee=np.maximum(a*fee_rate/100.0,np.where(np.isfinite(fee_floor),fee_floor,-np.inf)); fee=np.minimum(fee,np.where(np.isfinite(fee_cap),fee_cap,np.inf))
            fc=fee*rate/100.0; fc=np.maximum(fc,np.where(np.isfinite(comm_floor),comm_floor,-np.inf)); fc=np.minimum(fc,np.where(np.isfinite(comm_cap),comm_cap,np.inf)); vals=np.where(fee_types,fc,vals)
        floor=pd.to_numeric(sub.get('floor',pd.Series(np.nan,index=sub.index)),errors='coerce').to_numpy(dtype=float); cap=pd.to_numeric(sub.get('cap',pd.Series(np.nan,index=sub.index)),errors='coerce').to_numpy(dtype=float)
        vals=np.where(np.isfinite(floor),np.maximum(vals,floor),vals); vals=np.where(np.isfinite(cap),np.minimum(vals,cap),vals)
        # Round half-up to the paisa. Remove binary float noise first: 0.5% of 1999 is 9.995, which
        # floats store as 9.99499999..., and must round to 10.00, not 9.99 (V62.6.210).
        vals=np.sign(vals)*np.floor(np.round(np.abs(vals)*100,6)+0.5)/100
        expected[pos]=vals; rule_ids[pos]=sub['rule_id'].astype(str).to_numpy()
    tx['expected_commission']=expected; tx['commission_rule_id']=rule_ids; tx['rate_status']='Rate Master Missing'; tx.loc[ambiguous,'rate_status']='Ambiguous Rate Rule'; tx.loc[applied,'rate_status']='Applied'
    # The approved master contains two IMPS MONEY TRANSFER schedules whose
    # amount ranges overlap through ₹5,000. The source label alone cannot tell
    # IMPS Cash from IMPS Transfer. Keep the row unresolved and state the exact
    # evidence needed; never choose a rate based only on the amount.
    imps_ambiguous = tx['rule_type'].eq('IMPS MONEY TRANSFER')
    if imps_ambiguous.any():
        tx.loc[imps_ambiguous,'expected_commission']=np.nan
        tx.loc[imps_ambiguous,'commission_rule_id']=None
        tx.loc[imps_ambiguous,'required_evidence_missing']=True
        tx.loc[imps_ambiguous,'condition_fail_reason']='IMPS Cash vs IMPS Transfer product variant is not present in the source transaction type; approved product mapping or a source discriminator is required.'
        tx.loc[imps_ambiguous,'rate_status']='Ambiguous Product Variant'

    # Rules with account-/customer-level eligibility cannot be settled from a
    # transaction row alone. If an explicit account identifier is supplied, enforce
    # the stated monthly cap deterministically; otherwise keep the calculated amount
    # visible but block it from settlement as evidence-required.
    if 'account_id' in tx.columns:
        account_id = on_unique(tx['account_id'].astype('string').fillna(''), lambda x: x.str.strip())
    else:
        account_id = pd.Series('', index=tx.index, dtype='string')
    mini_mask = tx['rule_type'].eq('MATM MINI STATEMENT') & applied
    if mini_mask.any():
        usable = mini_mask & account_id.ne('') & tx['transaction_date'].notna()
        if usable.any():
            period = tx.loc[usable,'transaction_date'].dt.to_period('M').astype(str)
            key = account_id.loc[usable] + '|' + period
            order = key.groupby(key).cumcount()
            keep = usable.copy(); keep.loc[usable] = order.lt(2).to_numpy()
            tx.loc[usable & ~keep,'expected_commission'] = 0.0
            tx.loc[usable,'condition_fail_reason'] = tx.loc[usable,'condition_fail_reason'].astype('string')
        missing_account = mini_mask & (account_id.eq('') | tx['transaction_date'].isna())
        if missing_account.any():
            tx.loc[missing_account,'required_evidence_missing']=True
            tx.loc[missing_account,'condition_fail_reason']='Account-level identifier and month are required to enforce the maximum 2 mini-statements per account per month.'
            tx.loc[missing_account,'rate_status']='Evidence Required'
    else:
        # No account-level identifier means the cap cannot be verified.
        missing_account = tx['rule_type'].eq('MATM MINI STATEMENT') & tx['expected_commission'].notna()
        if missing_account.any():
            tx.loc[missing_account,'required_evidence_missing']=True
            tx.loc[missing_account,'condition_fail_reason']='Account-level identifier is required to enforce the maximum 2 mini-statements per account per month.'
            tx.loc[missing_account,'rate_status']='Evidence Required'

    # First-time/eligibility conditions are explicit in the SBI source but are not
    # encoded by the generic transaction type itself. Do not treat every such row as
    # eligible unless the source supplies the required evidence.
    first_time_types = {'GREEN PIN GENERATION'}
    truthy = {'1', 'TRUE', 'YES', 'Y', 'FIRST TIME', 'FIRST-TIME', 'FIRST'}
    falsy = {'0', 'FALSE', 'NO', 'N', 'NOT FIRST TIME', 'REPEAT', 'SUBSEQUENT'}
    for typ in first_time_types:
        m = tx['rule_type'].eq(typ) & tx['expected_commission'].notna()
        if not m.any():
            continue
        flag_cols=[c for c in tx.columns if norm(c) in {'FIRST TIME','FIRST_TIME','IS FIRST TIME','IS_FIRST_TIME'}]
        if not flag_cols:
            tx.loc[m,'expected_commission']=np.nan
            tx.loc[m,'verified_expected_commission']=np.nan
            tx.loc[m,'required_evidence_missing']=True
            tx.loc[m,'condition_fail_reason']='First-time eligibility evidence is required by the SBI rule.'
            tx.loc[m,'rate_status']='Evidence Required'
            continue
        flag_col=flag_cols[0]
        flag=on_unique(tx[flag_col].astype('string').fillna(''), lambda x: x.str.strip().str.upper())
        yes=m & flag.isin(truthy)
        no=m & flag.isin(falsy)
        unknown=m & ~flag.isin(truthy | falsy)
        # Explicitly non-first-time transactions are ineligible: do not pay the
        # first-time commission. Unknown/blank flags remain unresolved, not guessed.
        tx.loc[no,'expected_commission']=0.0
        tx.loc[no,'verified_expected_commission']=0.0
        tx.loc[no,'condition_failure']=True
        tx.loc[no,'condition_fail_reason']='SBI first-time-only condition not met.'
        tx.loc[no,'rate_status']='Condition Not Met'
        tx.loc[unknown,'expected_commission']=np.nan
        tx.loc[unknown,'verified_expected_commission']=np.nan
        tx.loc[unknown,'required_evidence_missing']=True
        tx.loc[unknown,'condition_fail_reason']='First-time flag is present but not a recognized yes/no value.'
        tx.loc[unknown,'rate_status']='Evidence Required'

    if applied.any() and 'rule_status' in r.columns:
        status=r.iloc[best_rule[applied]]['rule_status'].astype(str).str.upper().str.strip().to_numpy()
        pos=np.flatnonzero(applied); pend=status=='MAPPING TO CONFIRM'; tx.loc[tx.index[pos[pend]],'rate_status']='Applied - Pending Mapping'
    # Generic IMPS label cannot select Cash vs Transfer, even if a legacy rule matches.
    generic_imps = tx['rule_type'].eq('IMPS MONEY TRANSFER')
    if generic_imps.any():
        tx.loc[generic_imps,'expected_commission']=np.nan
        tx.loc[generic_imps,'commission_rule_id']=None
        tx.loc[generic_imps,'required_evidence_missing']=True
        tx.loc[generic_imps,'condition_fail_reason']='IMPS Cash vs IMPS Transfer product variant is not present in the source transaction type; approved product mapping or a source discriminator is required.'
        tx.loc[generic_imps,'rate_status']='Ambiguous Product Variant'
    # Product-level diagnostics for unmatched rows. This is deliberately grouped by
    # transaction type so a 300k-row source remains fast.
    miss_mask=pd.Series(missing,index=tx.index) & tx['rule_exists'].astype(bool)
    if miss_mask.any():
        for rule_type in tx.loc[miss_mask,'rule_type'].dropna().astype(str).unique():
            row_mask=miss_mask & tx['rule_type'].astype(str).eq(rule_type)
            rr=r[r['transaction_type'].eq(rule_type)]
            kyc_req=bool(rr.get('kyc_requirement',pd.Series('',index=rr.index)).fillna('').astype(str).str.strip().ne('').any())
            geo_req=bool(rr.get('channel',pd.Series('',index=rr.index)).fillna('').astype(str).str.strip().ne('').any())
            if kyc_req:
                missing_kyc=row_mask & on_unique(tx['kyc_type'].fillna('').astype(str), lambda x: x.str.strip()).eq('')
                if missing_kyc.any():
                    tx.loc[missing_kyc,'required_evidence_missing']=True
                    tx.loc[missing_kyc,'condition_fail_reason']='KYC/OVD evidence required by the SBI rule'
                    tx.loc[missing_kyc,'rate_status']='KYC Evidence Required'
                    row_mask=row_mask & ~missing_kyc
            if geo_req and row_mask.any():
                missing_geo=row_mask & on_unique(tx['channel'].fillna('').astype(str), lambda x: x.str.strip()).eq('')
                if missing_geo.any():
                    tx.loc[missing_geo,'required_evidence_missing']=True
                    tx.loc[missing_geo,'condition_fail_reason']='CSP geography required by the SBI rule'
                    tx.loc[missing_geo,'rate_status']='Geography Required'
                    row_mask=row_mask & ~missing_geo
            if row_mask.any():
                tx.loc[row_mask,'condition_failure']=True
                tx.loc[row_mask,'condition_fail_reason']='Transaction amount/date does not satisfy any executable SBI slab'
                tx.loc[row_mask,'rate_status']='Condition Failed'
    return tx,{'missing_rules':int((missing & ~tx['rule_exists'].to_numpy()).sum()),'condition_failures':int(tx['condition_failure'].sum()),'required_evidence':int(tx['required_evidence_missing'].sum()),'ambiguous_rules':int(ambiguous.sum()),'applied_rules':int(applied.sum()),'pending_mapping_rules':int((tx['rate_status'].astype(str).str.contains('Pending Mapping',na=False)).sum()),'transaction_rules':len(r)}

# ---------------------------------------------------------------------------
# Workbook-aware SBI master loader
# ---------------------------------------------------------------------------
# The SBI workbook supplied for this project is not a simple two-column rate
# table.  It contains a primary Expected Commission / Commission Master sheet
# plus separate slab schedules.  The loader below keeps that structure intact
# instead of forcing the workbook into a single generic `rate` column.

_LOCATION_RURAL = {'RURAL', 'SEMI URBAN', 'SEMI-URBAN', 'SEMIURBAN', 'RURAL/SEMI-URBAN'}
_LOCATION_URBAN = {'URBAN', 'METRO', 'URBAN/METRO'}


def _canonical_commercial_type(value):
    # Pure function of its input, called per row: cache string inputs.
    if type(value) is str: return _canonical_commercial_type_cached(value)
    return _canonical_commercial_type_uncached(value)

@lru_cache(maxsize=65536)
def _canonical_commercial_type_cached(value):
    return _canonical_commercial_type_uncached(value)

def _canonical_commercial_type_uncached(value):
    s = norm(value)
    aliases={
        'ACCOUNT OPENING (PMJDY)':'ACCOUNT OPPENING (PMJDY)',
        'SB ACCOUNT OPENING: WITH E-KYC (RATIONALE: PROMOTE E-KYC FOR OPERATIONAL EFFICIENCY)':'ACCOUNT OPPENING (PMJDY)',
        'SAVING ACCOUNT OPENING: WITHOUT E-KYC (WITH OVD-OFFICIALLY VALID DOCUMENTS)':'ACCOUNT OPPENING (PMJDY)',
        'SAVING ACCOUNT OPENING WITHOUT E-KYC WITH OVD':'ACCOUNT OPPENING (PMJDY)',
        'SAVING ACCOUNT OPENING WITHOUT E-KYC (WITH OVD)':'ACCOUNT OPPENING (PMJDY)',
        'SB ACCOUNT OPENING WITHOUT E-KYC WITH OVD':'ACCOUNT OPPENING (PMJDY)',
        'OPENING OF RD ACCOUNTS':'RD OPEN',
        'RD ACCOUNT OPENING':'RD OPEN',
        'OPENING STDR/FD':'STDR OPEN',
        'OPENING OF STDR/FD':'STDR OPEN',
        'STDR/FD OPEN':'STDR OPEN',
        'STDR FD OPEN':'STDR OPEN',
        'FIXED DEPOSIT OPEN':'STDR OPEN',
        'REMITTANCE (CASH) (TRANSACTION AMOUNT RS.100 & ABOVE) (NON-HOME BRANCH A/CS) (NO RECOVERY FROM CUSTOMERS)':'FUNDTRANSFER - NON HOME',
        'REMITTANCE (CASH)':'FUNDTRANSFER - NON HOME',
        'REMITTANCE CASH':'FUNDTRANSFER - NON HOME',
        'FUNDTRANSFER NON HOME':'FUNDTRANSFER - NON HOME',
        'FUND TRANSFER NON HOME':'FUNDTRANSFER - NON HOME',
        'REMITTANCE (TRANSFER) (HOME BRANCH A/CS) (NO RECOVERY FROM CUSTOMERS)':'FUNDTRANSFER - HOME',
        'REMITTANCE (TRANSFER)':'FUNDTRANSFER - HOME',
        'REMITTANCE TRANSFER':'FUNDTRANSFER - HOME',
        'FUNDTRANSFER HOME':'FUNDTRANSFER - HOME',
        'FUND TRANSFER HOME':'FUNDTRANSFER - HOME',
        'IMPS - CASH (UP TO RS. 5,000/-) NOTE-(RECOVERY FROM CUSTOMERS: 0.70% OF REMITTANCE AMOUNT, MIN RS.10/- AND MAX RS.35/-)':'IMPS CASH',
        'IMPS - CASH':'IMPS CASH',
        'IMPS (TRANSFER) (UP TO RS.30,000/-) (RECOVERY FROM CUSTOMERS: 0.70% OF REMITTANCE AMOUNT, MIN RS.10/- AND MAX RS.100/-)':'IMPS TRANSFER',
        'IMPS - TRANSFER':'IMPS TRANSFER',
        'IMPS FUNDTRANSFER':'IMPS FUNDTRANFER',
        'IMPS FUND TRANSFER':'IMPS FUNDTRANFER',
        'IMPS CASH':'IMPS CASH',
        'IMPS TRANSFER':'IMPS TRANSFER',
    }
    if s.startswith('SB ACCOUNT OPENING') or s.startswith('SAVING ACCOUNT OPENING') or s.startswith('SAVINGS ACCOUNT OPENING'):
        return 'ACCOUNT OPPENING (PMJDY)'
    if s.startswith('RD ACCOUNT OPENING') or s.startswith('OPENING OF RD ACCOUNTS'):
        return 'RD OPEN'
    if s.startswith('CASH WITHDRAWAL'):
        return 'CASH WITHDRAWAL'
    if s.startswith('CASH DEPOSIT'):
        return 'CASH DEPOSIT'
    if s.startswith('LOAN DEPOSIT'):
        return 'LOAN DEPOSIT'
    if s.startswith('STDR OPEN') or s.startswith('OPENING STDR'):
        return 'STDR OPEN'
    if s.startswith('BBPS'):
        return s
    return aliases.get(s,s)


def _read_sbi_pdf_style_sheet(content, sheet_name):
    """Read the 4-page SBI commission PDF converted to Excel.

    This format is a presentation table rather than the structured Commission
    Master format. Headers are repeated and merged cells shift the particulars
    and rural/urban rate columns between sections. Build the same normalized
    fields expected by the downstream rate engine without inferring rates from
    actual payouts.
    """
    from io import BytesIO
    raw = excel_io.read_excel(content, sheet_name=sheet_name, header=None, engine='openpyxl')
    rows=[]
    current_component=''
    for _, rr in raw.iterrows():
        vals=[None if pd.isna(x) else x for x in rr.tolist()]
        texts=[norm(x) for x in vals]
        if 'PARTICULARS' in texts and any('DETAILS/AMOUNT/TXN LIMIT' in x for x in texts):
            continue
        # In this workbook particulars appear in column C on page 1/2 and
        # column B on page 3/4; details consistently appear in column D.
        c2=vals[1] if len(vals)>1 else None
        c3=vals[2] if len(vals)>2 else None
        component = c2 if isinstance(c2,str) and str(c2).strip() else c3 if isinstance(c3,str) and str(c3).strip() else None
        detail = vals[3] if len(vals)>3 else None
        if component:
            current_component=str(component).strip()
        if not current_component or not detail and not any(vals[4:]):
            continue
        # Rural/Semiurban is column E in the first table and F in the later
        # repeated-header tables. Urban/Metro is G or H respectively.
        rural = vals[4] if len(vals)>4 and vals[4] is not None else (vals[5] if len(vals)>5 else None)
        urban = vals[6] if len(vals)>6 and vals[6] is not None else (vals[7] if len(vals)>7 else None)
        # In the SBI presentation table a single merged commission cell means
        # the same amount applies to both Rural/Semiurban and Urban/Metro.
        # Preserve the explicit 'Not Applicable' exception for Rural CSP.
        if urban is None and rural is not None and 'RURAL CSP' not in norm(current_component):
            urban = rural
        # BBPS is split into product-specific rules by the detail row.
        # Normalize those names now so they match the successful transaction
        # canonical labels used by the reconciliation engine.
        if norm(current_component) == 'BBPS':
            dnorm=norm(detail or '')
            if 'ELECTRICITY' in dnorm or 'GAS' in dnorm or 'WATER' in dnorm:
                current_rule_component='BBPS - ELECTRICITY'
            elif 'TELECOM' in dnorm or 'MOBILE' in dnorm or 'LANDLINE' in dnorm or 'BROADBAND' in dnorm:
                current_rule_component='BBPS - TELECOM'
            elif 'DTH' in dnorm:
                current_rule_component='BBPS - DTH'
            else:
                current_rule_component=current_component
        else:
            current_rule_component=current_component
        # Ignore pure section/header rows with no commercial value.
        rate_text=' '.join(str(x) for x in (rural,urban) if x is not None)
        if not rate_text.strip():
            continue
        rows.append({
            'component': current_rule_component,
            'sub_category_rule': '' if detail is None else str(detail),
            'expected_commission_rural_semi_urban': rural,
            'expected_commission_urban_metro': urban,
            'rate': pd.NA,
            'rate_type': '',
            'enrollment_type': 'TRANSACTIONAL',
            'effective_from': '01.04.2025',
            'source': 'SBI Updated Commission Structure Applicable From 01.04.2025',
            'remarks': 'CONFIRMED - uploaded SBI commission structure',
            'rate_schedule': '',
        })
    return pd.DataFrame(rows)

def _read_master_sheet(content, sheet_name, header_row=3):
    from io import BytesIO
    df = excel_io.read_excel(content, sheet_name=sheet_name, header=header_row, engine='openpyxl')
    df = df.dropna(how='all').copy()
    df.columns = (df.columns.astype(str).str.strip().str.lower()
                  .str.replace(r'[^a-z0-9]+', '_', regex=True).str.strip('_'))
    return df


def _numeric_or_none(v):
    # Accept only genuinely numeric cells. Do not extract digits from explanatory
    # text such as '50% of fee ... max Rs 50'.
    if v is None or (isinstance(v,float) and pd.isna(v)):
        return None
    if isinstance(v,(int,float)) and not isinstance(v,bool):
        return float(v) if pd.notna(v) else None
    text=str(v).strip().replace(',','')
    if re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', text):
        try: return float(text)
        except Exception: return None
    return None


def _same_or_number(v, other=None):
    n = _numeric_or_none(v)
    if n is not None:
        return n
    s = norm(v)
    if s in {'SAME', 'SAME VALUE', 'SAME AS RURAL'} and other is not None:
        return _numeric_or_none(other)
    return None


def _parse_percent_text(v):
    s = '' if v is None else str(v).strip()
    m = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*%', s)
    if not m:
        return None
    return float(m.group(1))


def _infer_status(remarks, explicit_status=None):
    st = norm(explicit_status)
    if st:
        return st
    r = norm(remarks)
    if not r:
        return 'CONFIRMED'
    if 'VALUE MISSING' in r or 'NO VALUE' in r:
        return 'VALUE MISSING'
    if 'MAPPING TO CONFIRM' in r or 'PLEASE CONFIRM' in r:
        return 'TO CONFIRM'
    return 'CONFIRMED'


def _build_base_rows(primary, source_kind):
    """Convert either Expected Commission or Commission Master to row records."""
    p = primary.copy()
    # Expected Commission workbook
    if 'component' in p.columns:
        p['component'] = p['component'].replace('', pd.NA).ffill()
        p['transaction_type'] = p['component'].map(_canonical_commercial_type)
        p['sub_category'] = p.get('sub_category_rule', pd.Series('', index=p.index)).fillna('').astype(str)
        p['rate_rural_raw'] = p.get('expected_commission_rural_semi_urban', pd.Series(pd.NA, index=p.index))
        p['rate_urban_raw'] = p.get('expected_commission_urban_metro', pd.Series(pd.NA, index=p.index))
        p['rate_pct_raw'] = p.get('rate', pd.Series(pd.NA, index=p.index))
        p['avg_per_enrollment'] = p.get('excel_avg_per_enrollment_revenue', pd.Series(pd.NA, index=p.index))
        p['rate_type_raw'] = p.get('rate_type', pd.Series('', index=p.index))
        p['enrollment_type'] = p.get('enrollment_type', pd.Series('', index=p.index))
        p['commission_cycle'] = p.get('commission_cycle', pd.Series('', index=p.index))
        p['source'] = p.get('source', pd.Series('', index=p.index))
        p['remarks'] = p.get('remarks', pd.Series('', index=p.index))
        p['rate_schedule'] = p.get('rate_schedule', pd.Series('', index=p.index))
        p['rule_id'] = 'RM-EC-' + (p.index + 1).astype(str)
        p['status'] = p['remarks'].map(_infer_status)
    else:
        # Commission Master workbook
        p['transaction_type'] = p.get('component_product', p.get('component', pd.Series('', index=p.index))).map(_canonical_commercial_type)
        p['sub_category'] = p.get('sub_category_rule', pd.Series('', index=p.index)).fillna('').astype(str)
        p['rate_rural_raw'] = p.get('rural_semi_urban_rate_rs', pd.Series(pd.NA, index=p.index))
        p['rate_urban_raw'] = p.get('urban_metro_rate_rs', pd.Series(pd.NA, index=p.index))
        p['cap_rural_raw'] = p.get('max_cap_rs_rural', pd.Series(pd.NA, index=p.index))
        p['cap_urban_raw'] = p.get('max_cap_rs_urban', pd.Series(pd.NA, index=p.index))
        p['rate_pct_raw'] = p.get('rate', pd.Series(pd.NA, index=p.index))
        p['rate_type_raw'] = p.get('rate_type', pd.Series('', index=p.index))
        p['avg_per_enrollment'] = p.get('excel_avg_per_enrollment_revenue', pd.Series(pd.NA, index=p.index))
        p['enrollment_type'] = p.get('enrollment_type', pd.Series('', index=p.index))
        p['commission_cycle'] = p.get('commission_cycle', pd.Series('', index=p.index))
        p['source'] = p.get('source', pd.Series('', index=p.index))
        p['remarks'] = p.get('remarks', pd.Series('', index=p.index))
        p['rate_schedule'] = p.get('rate_schedule', pd.Series('', index=p.index))
        p['rule_id'] = p.get('ref', 'RM-CM-' + (p.index + 1).astype(str)).fillna('')
        p['status'] = p.get('status', pd.Series('', index=p.index)).map(lambda x: _infer_status('', x))
    return p


def _schedule_map_for_expected(component):
    c = _canonical_commercial_type(component)
    return {
        'CASH WITHDRAWAL': 'SCH-CW',
        'AEPS ONUS WITHDRAWAL': 'SCH-CW',
        'CASH DEPOSIT': 'SCH-CD',
        'MATM ONUS DEPOSIT': 'SCH-CD',
        'AEPS ONUS DEPOSIT': 'SCH-CD',
        'LOAN DEPOSIT': 'SCH-CD',
        'FUNDTRANSFER - HOME': 'SCH-RT',
        'MATM ONUS FUNDSTRANSFER - HOME': 'SCH-RT',
        'AEPS ONUS FUNDTRANSFER - HOME': 'SCH-RT',
        'FUNDTRANSFER - NON HOME': 'SCH-RC',
    }.get(c)


def _schedule_rows(schedule_df, schedule_id):
    if schedule_df is None or schedule_df.empty or not schedule_id:
        return []
    s = schedule_df.copy()
    if 'schedule_id' not in s.columns:
        return []
    s = s[s['schedule_id'].astype(str).str.strip().str.upper().eq(schedule_id.upper())].copy()
    rows=[]
    for _,x in s.iterrows():
        calc=norm(x.get('calculation',''))
        rf=_numeric_or_none(x.get('rural_fixed_rs'))
        uf=_numeric_or_none(x.get('urban_fixed_rs'))
        rp=_numeric_or_none(x.get('rural_rate'))
        up=_numeric_or_none(x.get('urban_rate'))
        # Rate schedules store percentages as fractions (0.005 = 0.50%).
        if rp is not None and 0 < rp <= 1: rp *= 100
        if up is not None and 0 < up <= 1: up *= 100
        rows.append({
            'min_amount': _numeric_or_none(x.get('txn_amount_from')),
            'max_amount': _numeric_or_none(x.get('txn_amount_to')),
            'rate_type': 'PERCENTAGE' if '% OF AMOUNT' in calc else 'FIXED',
            'rate_rural': rp if rp is not None else rf,
            'rate_urban': up if up is not None else uf,
            'floor_rural': _numeric_or_none(x.get('rural_min')),
            'cap_rural': _numeric_or_none(x.get('rural_max')),
            'floor_urban': _numeric_or_none(x.get('urban_min')),
            'cap_urban': _numeric_or_none(x.get('urban_max')),
            'schedule_id': schedule_id,
        })
    return rows



def _expected_slab_rows(schedule_df, schedule_id):
    """Parse the 'Slab Rates' sheet used by SBI_Expected_Commission_Sheet.xlsx."""
    if schedule_df is None or schedule_df.empty:
        return []
    s=schedule_df.copy()
    if 'service' not in s.columns or 'transaction_amount' not in s.columns:
        return []
    s['service']=s['service'].replace('',pd.NA).ffill()
    mapping={
        'SCH-CW':'CASH WITHDRAWAL',
        'SCH-CD':'CASH DEPOSIT',
        'SCH-RC':'REMITTANCE (CASH) - NON-HOME BRANCH A/CS',
        'SCH-RT':'REMITTANCE (TRANSFER) - HOME BRANCH A/CS',
    }
    target=mapping.get(schedule_id,'')
    out=[]
    for _,x in s.iterrows():
        service=norm(x.get('service',''))
        if target and target not in service and not (schedule_id=='SCH-CD' and 'CASH DEPOSIT' in service) and not (schedule_id=='SCH-CW' and 'CASH WITHDRAWAL' in service):
            continue
        amt=norm(x.get('transaction_amount',''))
        mn=mx=None
        m=re.search(r'UP TO\s*RS\.?\s*([0-9][0-9,]*)',amt)
        if m: mx=float(m.group(1).replace(',',''))
        m=re.search(r'RS\.?\s*([0-9][0-9,]*)\s*[-–]\s*([0-9][0-9,]*)',amt)
        if m:
            mn=float(m.group(1).replace(',','')); mx=float(m.group(2).replace(',',''))
        rr=x.get('rural_semi_urban'); ur=x.get('urban_metro')
        rtxt='' if pd.isna(rr) else str(rr)
        utxt='' if pd.isna(ur) else str(ur)
        rp=_parse_percent_text(rtxt); up=_parse_percent_text(utxt)
        rf=None if rp is not None else _numeric_or_none(rr)
        uf=None if up is not None else _numeric_or_none(ur)
        rmin=rmax=umin=umax=None
        mr=re.search(r'MIN\s*RS\.?\s*([0-9][0-9,]*)',rtxt.upper())
        mxr=re.search(r'MAX\s*RS\.?\s*([0-9][0-9,]*)',rtxt.upper())
        mu=re.search(r'MIN\s*RS\.?\s*([0-9][0-9,]*)',utxt.upper())
        mxu=re.search(r'MAX\s*RS\.?\s*([0-9][0-9,]*)',utxt.upper())
        if mr:rmin=float(mr.group(1).replace(',',''))
        if mxr:rmax=float(mxr.group(1).replace(',',''))
        if mu:umin=float(mu.group(1).replace(',',''))
        if mxu:umax=float(mxu.group(1).replace(',',''))
        if rp is not None: rf=rp
        if up is not None: uf=up
        if mx is not None and mn is None:
            # Cash Deposit/Withdrawal/Non-home remittance require Rs 100+;
            # home transfer has no minimum according to the workbook note.
            mn=0 if schedule_id=='SCH-RT' else 100
        if rp is None and up is None and rf is None and uf is None:
            continue
        out.append({'min_amount':mn,'max_amount':mx,'rate_rural':rf,'rate_urban':uf,
                    'rate_type':'PERCENTAGE' if rp is not None or up is not None else 'FIXED',
                    'floor_rural':rmin,'cap_rural':rmax,'floor_urban':umin,'cap_urban':umax})
    return out


def _text_amount_bounds(text):
    """Extract simple inclusive/exclusive amount tiers from SBI rule text."""
    t=norm(text).replace('≥','>=').replace('≤','<=')
    mn=mx=None; mn_ex=False; mx_ex=False
    m=re.search(r'(?:INITIAL DEPOSIT|DEPOSIT).*?>=\s*RS\.?\s*([0-9][0-9,]*)',t)
    if m: mn=float(m.group(1).replace(',',''))
    m=re.search(r'>=\s*RS\.?\s*([0-9][0-9,]*)\s+TO\s*<\s*RS\.?\s*([0-9][0-9,]*)',t)
    if m:
        mn=float(m.group(1).replace(',','')); mx=float(m.group(2).replace(',','')); mx_ex=True
    m=re.search(r'INITIAL DEPOSIT\s*<\s*RS\.?\s*([0-9][0-9,]*)',t)
    if m: mx=float(m.group(1).replace(',','')); mx_ex=True
    m=re.search(r'BILL\s+UP\s+TO\s*RS\.?\s*([0-9][0-9,]*)',t)
    if m: mx=float(m.group(1).replace(',',''))
    m=re.search(r'BILL\s+ABOVE\s+RS\.?\s*([0-9][0-9,]*)',t)
    if m: mn=float(m.group(1).replace(',','')); mn_ex=True
    m=re.search(r'(?:UP TO|UPTO)\s*RS\.?\s*([0-9][0-9,]*)',t)
    if m and mx is None: mx=float(m.group(1).replace(',',''))
    # The SBI master uses both "MIN DEPOSIT RS 50" (RD) and
    # "DEPOSIT ... MIN RS ..." phrasings. Preserve both forms.
    m=re.search(r'MIN\s+DEPOSIT\s+RS\.?\s*([0-9][0-9,]*)',t)
    if m and mn is None: mn=float(m.group(1).replace(',',''))
    m=re.search(r'(?:AMOUNT|DEPOSIT).*?MIN\s*RS\.?\s*([0-9][0-9,]*)',t)
    if m and mn is None: mn=float(m.group(1).replace(',',''))
    return mn,mx,mn_ex,mx_ex

def _emit_rule(rules, base, *, rate_rural=None, rate_urban=None, rate_type='FIXED',
               min_amount=None, max_amount=None, min_exclusive=False, max_exclusive=False,
               floor_rural=None, cap_rural=None, floor_urban=None, cap_urban=None,
               schedule_id=None, channel=None, basis=None):
    # Treat the word "Same" as same rate, never as zero.
    if rate_urban is None and rate_rural is not None:
        rate_urban = rate_rural if norm(base.get('urban_raw','')) in {'SAME','SAME VALUE','SAME AS RURAL'} else rate_urban
    if rate_rural is None and rate_urban is not None and norm(base.get('rural_raw','')) in {'SAME','SAME VALUE','SAME AS URBAN'}:
        rate_rural = rate_urban
    # A rule with genuinely different geography must not silently choose one.
    pairs=[]
    same_rate = rate_rural is not None and rate_urban is not None and abs(rate_rural-rate_urban) < 1e-12
    same_floor = (floor_rural is None and floor_urban is None) or (floor_rural is not None and floor_urban is not None and abs(floor_rural-floor_urban) < 1e-12)
    same_cap = (cap_rural is None and cap_urban is None) or (cap_rural is not None and cap_urban is not None and abs(cap_rural-cap_urban) < 1e-12)
    if same_rate and same_floor and same_cap:
        pairs=[(None,rate_rural,floor_rural,cap_rural)]
    else:
        if rate_rural is not None: pairs.append(('RURAL',rate_rural,floor_rural,cap_rural))
        if rate_urban is not None: pairs.append(('URBAN',rate_urban,floor_urban,cap_urban))
    for loc,rate,floor,cap in pairs:
        rr={
            'rule_id': str(base.get('rule_id','')) + (f'-{loc}' if loc else ''),
            'transaction_type': _canonical_commercial_type(base.get('transaction_type','')),
            'sub_category': base.get('sub_category',''),
            'rate': rate,
            'rate_type': rate_type or 'FIXED',
            'fixed_fee': base.get('fixed_fee'),
            'min_amount': min_amount,
            'max_amount': max_amount,
            'max_exclusive': bool(max_exclusive),
            'min_exclusive': bool(min_exclusive),
            'cap': cap,
            'floor': floor,
            'effective_from': base.get('effective_from'),
            'effective_to': base.get('effective_to'),
            'csp_id': base.get('csp_id',''),
            'channel': loc or '',
            'priority': 10 if schedule_id else 0,
            'allowed_months': base.get('allowed_months',''),
            'commercial_scope': base.get('commercial_scope','TRANSACTION'),
            'rule_status': base.get('status','CONFIRMED'),
            'source': base.get('source',''),
            'remarks': base.get('remarks',''),
            'rate_schedule': schedule_id or '',
            'basis': basis or '',
        }
        rules.append(rr)




def _read_consolidated_sbi_commission_master(content, sheet_name):
    """Adapt the consolidated SBI expected-commission workbook to the deterministic rule engine."""
    from io import BytesIO
    raw = excel_io.read_excel(content, sheet_name=sheet_name, header=3, engine='openpyxl')
    raw = raw.dropna(how='all').copy()
    required = {'Category / Service', 'Component / Particulars', 'Slab / Condition / Details',
                'Rural / Semi-Urban (INR)', 'Urban / Metro (INR)', 'Type & Cycle'}
    if not required.issubset(set(raw.columns.astype(str))):
        raise ValueError("Consolidated SBI rule master has an unexpected column layout.")
    rows = []
    for i, row in raw.iterrows():
        component = str(row.get('Component / Particulars') or '').strip()
        if not component or component.lower() == 'nan':
            continue
        detail = '' if pd.isna(row.get('Slab / Condition / Details')) else str(row.get('Slab / Condition / Details')).strip()
        rural = row.get('Rural / Semi-Urban (INR)')
        urban = row.get('Urban / Metro (INR)')
        type_cycle = '' if pd.isna(row.get('Type & Cycle')) else str(row.get('Type & Cycle')).strip()
        parts = [x.strip() for x in type_cycle.split('|', 1)]
        scope_label = norm(parts[0] if parts else '')
        cycle = parts[1] if len(parts) > 1 else ''
        scope = 'TRANSACTIONAL' if scope_label in {'TRANSACTIONAL', 'COMMISSION'} else 'NON_TRANSACTION'
        if norm(component).startswith('PMJJBY - Q'):
            component = 'PMJJBY'
        elif norm(component).startswith('PMSBY (PRADHAN MANTRI SURAKSHA BIMA)'):
            component = 'PMSBY'
        txt = norm(detail)
        low = high = None
        low_ex = high_ex = False
        # Account-opening slabs use inclusive lower and sometimes exclusive upper limits.
        if 'INITIAL DEPOSIT' in txt or 'DEPOSIT' in txt:
            m = re.search(r'(?:INITIAL DEPOSIT|DEPOSIT)\s*(?:>=|≥)\s*(?:RS\.?\s*)?([0-9][0-9,]*)', txt)
            if m:
                low = float(m.group(1).replace(',', ''))
            m = re.search(r'(?:INITIAL DEPOSIT|DEPOSIT)\s*([0-9][0-9,]*)\s*TO\s*<\s*(?:RS\.?\s*)?([0-9][0-9,]*)', txt)
            if m:
                low = float(m.group(1).replace(',', ''))
                high = float(m.group(2).replace(',', ''))
                high_ex = True
            m = re.search(r'(?:INITIAL DEPOSIT|DEPOSIT)\s*<\s*(?:RS\.?\s*)?([0-9][0-9,]*)', txt)
            if m:
                high = float(m.group(1).replace(',', ''))
                high_ex = True
        if low is None and high is None and 'AGE ' not in txt:
            m = re.search(r'(?:RS\.?\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:/-)?\s*(?:TO|–|—|-)\s*(?:RS\.?\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)', txt)
            if m:
                low = float(m.group(1).replace(',', ''))
                high = float(m.group(2).replace(',', ''))
            else:
                m = re.search(r'(?:UP TO|UPTO|<=|≤)\s*(?:RS\.?\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)', txt)
                if m: high = float(m.group(1).replace(',', ''))
                m = re.search(r'(?:ABOVE|>)\s*(?:RS\.?\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)', txt)
                if m:
                    low = float(m.group(1).replace(',', ''))
                    low_ex = True
        original_component = component
        component_norm = norm(component)
        remarks = 'CONFIRMED - source row parsed; unresolved formulae remain non-executable'
        # Align service names to the existing BC-side canonical labels where the
        # supplied master makes the service identity explicit.
        if component_norm == 'OPENING OF RD ACCOUNTS': component = 'RD OPEN'
        elif component_norm == 'NEFT BY TRANSFER': component = 'NEFT'
        elif component_norm == 'MOBILE SEEDING': component = 'MOBILE NUMBER SEEDING'
        elif component_norm == 'CHEQUE BOOK ISSUANCE REQUEST': component = 'CHEQUE BOOK ISSUE REQUEST'
        # Canonicalize product labels only where the source semantics are explicit.
        if component_norm.startswith('PMJJBY - Q'):
            component = 'PMJJBY'
        if component_norm.startswith('SB ACCOUNT OPENING'):
            kyc_hint = 'OVD' if ('NON-EKYC' in component_norm or 'OVD' in component_norm) else 'EKYC'
            component = 'ACCOUNT OPPENING (PMJDY)'
        else:
            kyc_hint = ''
        if component_norm.startswith('REMITTANCE (CASH)') or component_norm.startswith('REMITTANCE (TRANSFER)') or component_norm.startswith('FUND TRANSFER - NON HOME'):
            component = 'MONEY TRANSFER'
            remarks = 'MAPPING TO CONFIRM - source does not expose home/non-home branch evidence for selecting this product rule'
        if component_norm == 'IMPS - CASH':
            component = 'IMPS CASH'
        elif component_norm == 'IMPS - TRANSFER':
            component = 'IMPS TRANSFER'
        if component_norm.startswith('BBPS - UTILITIES'):
            detail_norm = norm(detail)
            if 'DTH' in detail_norm:
                component = 'BBPS - DTH'
            elif 'ELECTRICITY' in detail_norm or 'GAS' in detail_norm or 'WATER' in detail_norm:
                component = 'BBPS - ELECTRICITY'
            elif 'TELECOM' in detail_norm:
                component = 'BBPS - TELECOM'
            # "80% of CCF (Rs. 4/- per bill)": the bracketed amount IS the commission per bill
            # (80% of the customer convenience fee), confirmed by the business on 2026-10-29
            # (V62.6.210). It is a fixed amount per bill, not 80% of the bill or of Rs 4.
            for cell_name, cell_value in [('rural', rural), ('urban', urban)]:
                cell = str(cell_value)
                ccf = re.search(r'CCF\s*\(\s*RS\.?\s*([0-9][0-9,]*(?:\.[0-9]+)?)', cell.upper())
                pct = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*%', cell)
                if ccf and pct:
                    calculated = float(ccf.group(1).replace(',', ''))
                    if cell_name == 'rural': rural = f"Rs {calculated:.2f}"
                    else: urban = f"Rs {calculated:.2f}"
        # These rules require evidence/logic not present in transaction-level source alone.
        if component_norm == 'APY (ATAL PENSION YOJANA)':
            remarks = 'MAPPING TO CONFIRM - source states a ₹60–₹75 range but does not define which amount applies'
        if component_norm == 'PASSBOOK PRINTING':
            remarks = 'MAPPING TO CONFIRM - account-level maximum five prints per account/month requires account-level print evidence'
        if component_norm == 'MINI STATEMENT (MICRO ATM / AEPS)':
            remarks = 'MAPPING TO CONFIRM - maximum two statements per account/month requires account-level evidence'
        if component_norm.startswith('LOAN LEAD:'):
            remarks = 'MAPPING TO CONFIRM - commission base is sanction limit; uploaded transaction Amount is not proven to be sanction limit'
        if component_norm == 'DEPOSIT IN LOAN ACCOUNT - UNMAPPED':
            remarks = 'MAPPING TO CONFIRM - rate explicitly depends on Cash Deposit commission rule and account mapping'
        if component_norm == 'INACTIVITY PENALTY':
            remarks = 'MAPPING TO CONFIRM - penalty eligibility requires inactivity/onboarding evidence'
        if component_norm == 'AVERAGE BALANCE MAINTENANCE':
            remarks = 'MAPPING TO CONFIRM - average-balance source/base and monthly cap must be evidenced'
        allowed_months = _month_rule(f"{original_component} {detail}")
        premium_match = re.search(r'PREMIUM\s*(?:RS\.?\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)', norm(detail))
        if premium_match and norm(component) in {'PMJJBY','PMSBY'}:
            low = high = float(premium_match.group(1).replace(',', ''))
        kyc = kyc_hint
        rows.append({
            'component': component, 'sub_category_rule': detail,
            'expected_commission_rural_semi_urban': rural,
            'expected_commission_urban_metro': urban, 'rate': pd.NA,
            'rate_type': ('RANGE' if norm(original_component).startswith('APY (ATAL PENSION') and re.search(r'RS\.?\s*[0-9][0-9,]*(?:/-)?\s*(?:TO|-)\s*RS\.?\s*[0-9][0-9,]*', norm(str(rural))) else ('PERCENTAGE' if '%' in str(rural) or '%' in str(urban) else 'FIXED')),
            'enrollment_type': scope, 'commission_cycle': cycle,
            'source': 'SBI_Expected_Commission_Rule.xlsx — Consolidated Commission Master',
            'remarks': remarks,
            'rate_schedule': '', 'min_amount': low, 'max_amount': high,
            'min_exclusive': low_ex, 'max_exclusive': high_ex,
            'allowed_months': allowed_months, 'kyc_requirement': kyc,
            'source_rule_row': int(i) + 5,
        })
    return pd.DataFrame(rows)


def build_rate_master_from_workbook(content, filename='rate_master.xlsx', selected_sheet=None):
    """Read the complete SBI rate workbook, including auxiliary slab sheets.

    Returns a normalized deterministic rule table plus validation metadata.  No
    historical actuals are used to infer rates.  Rules that cannot be resolved
    from the workbook are retained as warnings rather than converted to zero.
    """
    from io import BytesIO
    xl = excel_io.excel_file(content)
    sheets = xl.sheet_names
    lower={norm(s):s for s in sheets}
    is_consolidated_master = 'CONSOLIDATED COMMISSION MASTER' in lower
    if is_consolidated_master:
        primary_name=lower['CONSOLIDATED COMMISSION MASTER']
        primary_rows=_build_base_rows(_read_consolidated_sbi_commission_master(content, primary_name), 'expected')
    elif selected_sheet and selected_sheet in sheets:
        primary_name=selected_sheet
    elif 'COMMISSION MASTER' in lower:
        primary_name=lower['COMMISSION MASTER']
    elif 'EXPECTED COMMISSION' in lower:
        primary_name=lower['EXPECTED COMMISSION']
    else:
        primary_name=sheets[0]
    # Structured project workbooks use a header on row 4, but the official SBI
    # 4-page commission-structure Excel export uses a presentation table whose
    # header is on row 3 and is repeated later. Detect that format explicitly.
    if 'CONSOLIDATED COMMISSION MASTER' in lower:
        # primary_rows already adapted from the user's consolidated rule workbook.
        pass
    elif 'COMMISSION MASTER' not in norm(primary_name) and 'EXPECTED COMMISSION' not in norm(primary_name):
        from io import BytesIO
        raw_probe=excel_io.read_excel(content,sheet_name=primary_name,header=None,engine='openpyxl',nrows=12)
        probe=' '.join(str(x).upper() for x in raw_probe.astype(str).fillna('').to_numpy().ravel())
        if 'PARTICULARS' in probe and 'DETAILS/AMOUNT/TXN LIMIT' in probe:
            primary_rows=_build_base_rows(_read_sbi_pdf_style_sheet(content,primary_name), 'expected')
        else:
            primary=_read_master_sheet(content,primary_name,3)
            primary_rows=_build_base_rows(primary, 'expected')
    else:
        primary=_read_master_sheet(content,primary_name,3)
        primary_rows=_build_base_rows(primary, 'commission_master' if 'COMMISSION MASTER' in norm(primary_name) else 'expected')

    slab_name=lower.get('SLAB RATES') or lower.get('RATE SCHEDULES')
    slab=None
    if slab_name:
        slab=_read_master_sheet(content,slab_name,3)
    rules=[]; unresolved=[]
    for _,row in primary_rows.iterrows():
        base=row.to_dict()
        component=_canonical_commercial_type(base.get('transaction_type',''))
        if not component or component in {'NONE','NAN'}:
            continue
        et=norm(base.get('enrollment_type',''))
        scope='TRANSACTION' if et in {'TRANSACTIONAL','COMMISSION'} else 'NON_TRANSACTION'
        base['commercial_scope']=scope
        base['allowed_months']=_month_rule(base.get('sub_category',''))
        status=_infer_status(base.get('remarks',''),base.get('status',''))
        base['status']=status
        rt=norm(base.get('rate_type_raw',''))
        rr=_same_or_number(base.get('rate_rural_raw'),base.get('rate_rural_raw'))
        ur=_same_or_number(base.get('rate_urban_raw'),base.get('rate_rural_raw'))
        raw_r=str(base.get('rate_rural_raw',''))
        raw_u=str(base.get('rate_urban_raw',''))
        # For percentage/slab text, parse the commission cap from each geography
        # cell rather than feeding the entire sentence to the numeric parser.
        cap_from_r=_numeric_or_none(base.get('cap_rural_raw'))
        cap_from_u=_numeric_or_none(base.get('cap_urban_raw'))
        floor_from_r=_numeric_or_none(base.get('floor_rural_raw'))
        floor_from_u=_numeric_or_none(base.get('floor_urban_raw'))
        mf=re.search(r'MIN\s*RS\.?\s*([0-9][0-9,]*(?:\.[0-9]+)?)',raw_r.upper())
        if mf: floor_from_r=float(mf.group(1).replace(',',''))
        mf=re.search(r'MIN\s*RS\.?\s*([0-9][0-9,]*(?:\.[0-9]+)?)',raw_u.upper())
        if mf: floor_from_u=float(mf.group(1).replace(',',''))
        mc=re.search(r'MAX\s*RS\.?\s*([0-9][0-9,]*(?:\.[0-9]+)?)',raw_r.upper())
        if mc: cap_from_r=float(mc.group(1).replace(',',''))
        mc=re.search(r'MAX\s*RS\.?\s*([0-9][0-9,]*)',raw_u.upper())
        if mc: cap_from_u=float(mc.group(1).replace(',',''))
        if norm(raw_u) in {'SAME','SAME VALUE','SAME AS RURAL'}: ur=rr
        if norm(raw_r) in {'SAME','SAME VALUE','SAME AS URBAN'}: rr=ur
        pct_text=_parse_percent_text(base.get('rate_rural_raw'))
        pct=_numeric_or_none(base.get('rate_pct_raw'))
        # IMPS commission is a percentage of the customer fee, not of the
        # transaction amount. The source explicitly provides the fee percentage,
        # fee floor/cap, and CSP commission floor/cap.
        fee_rate_pct=fee_min=fee_max=commission_min=commission_max=None
        if component in {'IMPS FUNDTRANFER','IMPS MONEY TRANSFER','IMPS CASH','IMPS TRANSFER'}:
            rrtext=norm(base.get('sub_category',''))
            mfee=re.search(r'CUSTOMER FEE\s*([0-9]+(?:\.[0-9]+)?)\s*%', rrtext)
            mmin=re.search(r'CUSTOMER FEE.*?MIN\s*RS\.?\s*([0-9][0-9,]*)', rrtext)
            mmax=re.search(r'CUSTOMER FEE.*?MAX\s*RS\.?\s*([0-9][0-9,]*)', rrtext)
            if mfee: fee_rate_pct=float(mfee.group(1))
            if mmin: fee_min=float(mmin.group(1).replace(',',''))
            if mmax: fee_max=float(mmax.group(1).replace(',',''))
            cmn=re.search(r'\(MIN\s*RS\.?\s*([0-9][0-9,]*)', str(base.get('rate_rural_raw','')).upper())
            cmx=re.search(r'MAX\s*RS\.?\s*([0-9][0-9,]*)', str(base.get('rate_rural_raw','')).upper())
            if cmn: commission_min=float(cmn.group(1).replace(',',''))
            if cmx: commission_max=float(cmx.group(1).replace(',',''))
            # The SBI screenshot provides explicit, product-specific fee/share bounds.
            # Keep these as permanent rules; never infer the product from amount alone.
            if component == 'IMPS CASH':
                fee_rate_pct, fee_min, fee_max, commission_min, commission_max = 0.70, 10.0, 35.0, 8.0, 28.0
            elif component == 'IMPS TRANSFER':
                fee_rate_pct, fee_min, fee_max, commission_min, commission_max = 0.70, 10.0, 100.0, 5.0, 50.0
        if pct_text is not None:
            # The Expected Commission sheet stores text such as 0.50%; keep it
            # as percentage points (0.50), not 0.005 and not 50.
            pct=pct_text
        elif pct is not None and 0 < pct <= 1:
            # Commission Master stores Rate % as a fraction (0.005 = 0.50%).
            pct=pct*100
        if 'PERCENT' in rt or '% OF' in rt or '% P.A.' in rt or pct_text is not None:
            if pct is not None:
                rr=pct if rr is None or pct_text is not None else rr
                ur=pct if ur is None or (pct_text is not None and norm(raw_u) not in {'SAME','SAME VALUE','SAME AS RURAL'}) else ur
            rate_type='PERCENTAGE'
        elif 'SLAB' in rt:
            rate_type='SLAB'
        elif 'RANGE' in rt:
            unresolved.append(f"{component}: rate range requires an approved selection rule ({base.get('remarks','')}).")
            continue
        else:
            rate_type='FIXED'
            # Fixed-rate text cells can contain explanatory text.  Never pass the
            # whole sentence through a loose numeric parser; extract the first
            # explicit rupee amount only.
            if rr is None:
                mrs=re.search(r'RS\.?\s*([0-9][0-9,]*(?:\.[0-9]+)?)',raw_r.upper())
                if mrs: rr=float(mrs.group(1).replace(',',''))
            if ur is None and norm(raw_u) not in {'SAME','SAME VALUE','SAME AS RURAL'}:
                mus=re.search(r'RS\.?\s*([0-9][0-9,]*(?:\.[0-9]+)?)',raw_u.upper())
                if mus: ur=float(mus.group(1).replace(',',''))
        # Expected Commission workbook slab mappings are explicitly documented by
        # service name. A pandas NaN is NOT a real schedule id. Most fixed/percentage
        # rows have a blank schedule cell, so never turn NaN into the literal string
        # "nan" and accidentally force them through slab parsing.
        schedule_id=''
        if slab is not None and pd.notna(base.get('rate_schedule')) and str(base.get('rate_schedule')).strip().lower() not in {'','nan','none'}:
            schedule_id=str(base.get('rate_schedule')).strip()
        if not schedule_id and rate_type=='SLAB':
            schedule_id=_schedule_map_for_expected(component) or ''

        # IMPS is a fee-share rule, not an amount-rate slab. The SBI workbook gives
        # the transaction cap, customer-fee formula/floor/cap, and CSP share/floor/cap
        # in the Rate Schedules sheet. Emit one deterministic FEE_PERCENTAGE rule so
        # calculate_expected() applies: customer fee -> CSP share -> CSP min/max.
        if component in {'IMPS FUNDTRANFER','IMPS MONEY TRANSFER','IMPS CASH','IMPS TRANSFER'}:
            schedule_id = str(base.get('rate_schedule')).strip() if pd.notna(base.get('rate_schedule')) else ''
            # The IMPS fee/share values live in the Rate Schedules sheet, not in
            # the primary commission-rate columns. Read that row directly so the
            # customer-fee percentage is never confused with the CSP share.
            if slab is not None and schedule_id:
                sr=slab[slab['schedule_id'].astype(str).str.strip().str.upper().eq(schedule_id.upper())].copy() if 'schedule_id' in slab.columns else pd.DataFrame()
                # Rate Schedules contains a second table (IMPS fee-based) with its
                # own header. The first header belongs to the amount slabs, so read
                # the IMPS table explicitly when needed.
                if schedule_id.upper().startswith('SCH-IMPS-') and 'RATE SCHEDULES' in norm(slab_name):
                    try:
                        from io import BytesIO
                        raw=excel_io.read_excel(content,sheet_name=slab_name,header=23,engine='openpyxl')
                        raw.columns=(raw.columns.astype(str).str.strip().str.lower().str.replace(r'[^a-z0-9]+','_',regex=True).str.strip('_'))
                        sr=raw[raw['schedule_id'].astype(str).str.strip().str.upper().eq(schedule_id.upper())].copy()
                    except Exception:
                        sr=pd.DataFrame()
                if not sr.empty:
                    sx=sr.iloc[0]
                    fee_rate_pct=_numeric_or_none(sx.get('customer_fee'))
                    if fee_rate_pct is not None and 0 < fee_rate_pct <= 1:
                        fee_rate_pct *= 100.0
                    fee_min=_numeric_or_none(sx.get('customer_fee_min'))
                    fee_max=_numeric_or_none(sx.get('customer_fee_max'))
                    share=_numeric_or_none(sx.get('csp_share_of_fee'))
                    commission_min=_numeric_or_none(sx.get('csp_min'))
                    commission_max=_numeric_or_none(sx.get('csp_max'))
                    max_txn=_numeric_or_none(sx.get('max_txn_amount'))
                else:
                    max_txn=None; share=None
            else:
                # Consolidated SBI rule master embeds the customer-fee formula
                # and CSP share/floor/cap in its row, so it can be evaluated
                # without a separate Rate Schedules worksheet.
                max_txn = _numeric_or_none(_text_amount_bounds(norm(base.get('sub_category','')))[1])
                share_pct = _parse_percent_text(raw_r)
                share = (share_pct / 100.0) if share_pct is not None else None
                if fee_rate_pct is None:
                    mfee=re.search(r'CUSTOMER FEE\s*([0-9]+(?:\.[0-9]+)?)\s*%', norm(base.get('sub_category','')))
                    if mfee: fee_rate_pct=float(mfee.group(1))
                if fee_min is None or fee_max is None:
                    mfee=re.search(r'CUSTOMER FEE.*?MIN\s*(?:RS\.?\s*)?([0-9][0-9,]*).*?MAX\s*(?:RS\.?\s*)?([0-9][0-9,]*)', norm(base.get('sub_category','')))
                    if mfee:
                        fee_min=float(mfee.group(1).replace(',','')); fee_max=float(mfee.group(2).replace(',',''))
                mcomm=re.search(r'MIN\s*RS\.?\s*([0-9][0-9,]*).*?MAX\s*RS\.?\s*([0-9][0-9,]*)', raw_r.upper())
                if mcomm:
                    commission_min=float(mcomm.group(1).replace(',','')); commission_max=float(mcomm.group(2).replace(',',''))
            if all(v is not None for v in (fee_rate_pct,fee_min,fee_max,share,commission_min,commission_max,max_txn)):
                _emit_rule(rules, base, rate_rural=share*100.0, rate_urban=share*100.0,
                           rate_type='FEE_PERCENTAGE', min_amount=0, max_amount=max_txn,
                           schedule_id=schedule_id,
                           basis=f'fee_rate={fee_rate_pct};fee_min={fee_min};fee_max={fee_max};commission_min={commission_min};commission_max={commission_max}')
                continue
            unresolved.append(f"{component}: fee/share schedule is incomplete in the uploaded workbook.")
            continue

        if rate_type=='SLAB' or schedule_id:
            sr=_schedule_rows(slab,schedule_id)
            if not sr:
                sr=_expected_slab_rows(slab,schedule_id)
            if sr:
                for j,x in enumerate(sr):
                    _emit_rule(rules,base,rate_rural=x['rate_rural'],rate_urban=x['rate_urban'],
                               rate_type=x['rate_type'],min_amount=x['min_amount'],max_amount=x['max_amount'],
                               floor_rural=x['floor_rural'],cap_rural=x['cap_rural'],
                               floor_urban=x['floor_urban'],cap_urban=x['cap_urban'],
                               schedule_id=schedule_id,basis='transaction_amount')
                continue
            unresolved.append(f"{component}: slab schedule {schedule_id or '(not identified)'} is not available in the uploaded workbook.")
            continue
        # STDR and other amount/rule caps from the primary sheet.
        txt=norm(base.get('sub_category',''))
        mn,mx,mn_ex,mx_ex=_text_amount_bounds(txt)
        # The consolidated expected-rule workbook already exposes explicit bounds
        # parsed from its condition column; use them when the prose parser cannot.
        explicit_min=_numeric_or_none(base.get('min_amount'))
        explicit_max=_numeric_or_none(base.get('max_amount'))
        if mn is None and explicit_min is not None: mn=explicit_min
        if mx is None and explicit_max is not None: mx=explicit_max
        mn_ex = bool(base.get('min_exclusive', mn_ex)) if pd.notna(base.get('min_exclusive', pd.NA)) else mn_ex
        mx_ex = bool(base.get('max_exclusive', mx_ex)) if pd.notna(base.get('max_exclusive', pd.NA)) else mx_ex
        mx_urban=None
        # Only STDR uses transaction-amount max/min language in the primary row.
        # IMPS 'min/max Rs' refers to the customer fee and must not become a
        # transaction-amount boundary.
        if component=='STDR OPEN':
            m=re.search(r'MIN\s*(?:RS\.?\s*)?([0-9][0-9,]*)',txt)
            if m: mn=float(m.group(1).replace(',',''))
            # SBI source wording varies between 'Max Rs 10,000 (Rural) / Rs 20,000 (Urban)'
            # and 'Max Rs 10,000 (for Rural) Max Rs 20,000 (for Urban)'.
            m=re.search(r'MAX\.?\s*(?:RS\.?\s*)?([0-9][0-9,]*)(K?)\s*\(RURAL\)',txt)
            if m:
                mx=float(m.group(1).replace(',','')) * (1000 if m.group(2)=='K' else 1)
            if mx is None:
                m=re.search(r'MAX\.?\s*(?:RS\.?\s*)?([0-9][0-9,]*)(K?)\s*\(FOR\s+RURAL\)',txt)
                if m: mx=float(m.group(1).replace(',','')) * (1000 if m.group(2)=='K' else 1)
            m=re.search(r'MAX\.?\s*(?:RS\.?\s*)?([0-9][0-9,]*)(K?)\s*\(FOR\s+URBAN\)',txt)
            if m: mx_urban=float(m.group(1).replace(',','')) * (1000 if m.group(2)=='K' else 1)
            if mx_urban is None:
                m=re.search(r'/\s*(?:RS\.?\s*)?([0-9][0-9,]*)(K?)\s*\(URBAN\)',txt)
                if m: mx_urban=float(m.group(1).replace(',','')) * (1000 if m.group(2)=='K' else 1)
            if mx_urban is None:
                m=re.search(r'/\s*([0-9][0-9,]*)(K?)\s*\(URBAN\)',txt)
                if m: mx_urban=float(m.group(1).replace(',','')) * (1000 if m.group(2)=='K' else 1)
        cap_r=cap_from_r
        cap_u=cap_from_u
        if component=='STDR OPEN' and mx_urban is not None:
            # Emit separate geography rules with transaction maximum and commission cap distinct.
            if rr is not None: _emit_rule(rules,base,rate_rural=rr,rate_urban=None,rate_type=rate_type,min_amount=mn,max_amount=mx,max_exclusive=mx_ex,cap_rural=cap_r)
            if ur is not None: _emit_rule(rules,base,rate_rural=None,rate_urban=ur,rate_type=rate_type,min_amount=mn,max_amount=mx_urban,max_exclusive=mx_ex,cap_urban=cap_u)
        else:
            # BBPS Electricity/Telecom in the source has two fixed tiers in one
            # cell: up to Rs 1,000 and above Rs 1,000. Expand those two tiers into
            # separate deterministic rules instead of choosing the first value.
            if component in {'BBPS - ELECTRICITY','BBPS - TELECOM'} and '/' in raw_r and 'BILL' in norm(raw_r):
                nums=[float(x.replace(',','')) for x in re.findall(r'RS\.?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*\(',raw_r.upper())]
                if len(nums)>=2:
                    rr, ur = nums[0], (nums[0] if norm(raw_u) in {'SAME','SAME VALUE','SAME AS RURAL'} else ur)
                    _emit_rule(rules,base,rate_rural=nums[0],rate_urban=nums[0] if norm(raw_u) in {'SAME','SAME VALUE','SAME AS RURAL'} else ur,rate_type='FIXED',max_amount=1000,cap_rural=cap_from_r,cap_urban=cap_from_u)
                    _emit_rule(rules,base,rate_rural=nums[1],rate_urban=nums[1] if norm(raw_u) in {'SAME','SAME VALUE','SAME AS RURAL'} else ur,rate_type='FIXED',min_amount=1000,min_exclusive=True,cap_rural=cap_from_r,cap_urban=cap_from_u)
                    continue
            # For fixed values, the primary rural/urban values are authoritative.
            # If both are missing but an explicit average exists, retain it only as
            # metadata; average revenue is not substituted for an approved rate.
            if rr is not None or ur is not None:
                _emit_rule(rules,base,rate_rural=rr,rate_urban=ur,rate_type=('FEE_PERCENTAGE' if component in {'IMPS FUNDTRANFER','IMPS MONEY TRANSFER','IMPS CASH','IMPS TRANSFER'} else rate_type),min_amount=mn,max_amount=mx,min_exclusive=mn_ex,max_exclusive=mx_ex,floor_rural=floor_from_r,cap_rural=cap_from_r,floor_urban=floor_from_u,cap_urban=cap_from_u,basis=(f'fee_rate={fee_rate_pct};fee_min={fee_min};fee_max={fee_max};commission_min={commission_min};commission_max={commission_max}' if component in {'IMPS FUNDTRANFER','IMPS MONEY TRANSFER','IMPS CASH','IMPS TRANSFER'} else ''))
            else:
                unresolved.append(f"{component}: no numeric approved rate was found; average-per-enrollment is not used as a substitute.")

    rules_df=pd.DataFrame(rules)
    if is_consolidated_master and not rules_df.empty:
        # The consolidated workbook is the permanent primary source, but it has
        # generic SBI service rows rather than every product-specific BC label
        # (e.g. AEPS ONUS withdrawal/deposit). Retain the existing approved
        # product-wise rate schedules only for BC transaction types that the new
        # master does not represent at all. Never add a legacy rule for a type
        # represented by a new row, even if that new row is blocked pending evidence.
        from pathlib import Path
        legacy_path = Path(__file__).resolve().parents[3] / 'docs' / 'approved_master' / 'SBI_CSP_Final_Commission.xlsx'
        if legacy_path.exists():
            try:
                legacy_rules, legacy_validation = build_rate_master_from_workbook(
                    legacy_path.read_bytes(), legacy_path.name
                )
                new_types = set(map_unique(rules_df['transaction_type'], norm))
                legacy_exclusions = {'LEAD GENERATION', 'MATM MINI STATEMENT', 'AEPS MINI STATEMENT - ACQUIRER UID', 'AEPS MINI STATEMENT - ONUS'}
                legacy_extra = legacy_rules[
                    ~map_unique(legacy_rules['transaction_type'], norm).isin(new_types | legacy_exclusions)
                ].copy()
                if not legacy_extra.empty:
                    for col in rules_df.columns:
                        if col not in legacy_extra.columns: legacy_extra[col] = pd.NA
                    for col in legacy_extra.columns:
                        if col not in rules_df.columns: rules_df[col] = pd.NA
                    rules_df = pd.concat([rules_df, legacy_extra[rules_df.columns]], ignore_index=True)
                    unresolved.append(
                        f'Legacy product-wise rule supplement retained {len(legacy_extra)} rule row(s) for BC product types absent from the consolidated SBI master; source statuses remain unchanged.'
                    )
            except Exception as exc:
                unresolved.append(f'Legacy product-wise rule supplement could not be loaded: {exc}')
    if not rules_df.empty and rules_df['rule_id'].duplicated(keep=False).any():
        counters={}
        new_ids=[]
        for rid in rules_df['rule_id'].astype(str):
            counters[rid]=counters.get(rid,0)+1
            new_ids.append(rid if counters[rid]==1 else f'{rid}-S{counters[rid]}')
        rules_df['rule_id']=new_ids
    if rules_df.empty:
        return rules_df, {
            'valid':False,'rows':0,'rules':0,'transaction_rules':0,
            'missing_columns':['commercial rules'],'errors':['No usable commercial rules were extracted from the workbook.'],
            'warnings':unresolved,'selected_sheet':primary_name,'available_sheets':sheets,
        }
    # Rules marked Value Missing / To Confirm are retained for audit visibility,
    # but only numeric deterministic rules participate in calculation.
    rules_df['transaction_type']=rules_df['transaction_type'].map(_canonical_commercial_type)

    # V54: user-supplied SBI commission rule supplement. The attached SBI rule
    # explicitly specifies PMJDY account-opening slabs and the social-security
    # enrollment payouts. These values take precedence over older/provisional
    # copies of the same product rules in the uploaded consolidated master.
    # Source: user-supplied SBI commission-rule image, supplied in this chat.
    # The supplement is deliberately limited to these exact products; it does not
    # infer rates for any other transaction type.
    _user_product_rules = pd.DataFrame([
        {'rule_id':'CM001','transaction_type':'ACCOUNT OPPENING (PMJDY)','sub_category':'CM001 - With e-KYC: initial deposit >= Rs 1000','rate':50.0,'rate_type':'FIXED','min_amount':1000.0,'max_amount':pd.NA,'max_exclusive':False,'min_exclusive':False,'allowed_months':'','kyc_requirement':'EKYC','rule_status':'CONFIRMED','commercial_scope':'TRANSACTION','priority':100,'source':'User-supplied SBI commission rule screenshot'},
        {'rule_id':'CM002','transaction_type':'ACCOUNT OPPENING (PMJDY)','sub_category':'CM002 - With e-KYC: initial deposit >= Rs 500 to < Rs 1000','rate':40.0,'rate_type':'FIXED','min_amount':500.0,'max_amount':1000.0,'max_exclusive':True,'min_exclusive':False,'allowed_months':'','kyc_requirement':'EKYC','rule_status':'CONFIRMED','commercial_scope':'TRANSACTION','priority':100,'source':'User-supplied SBI commission rule screenshot'},
        {'rule_id':'CM003','transaction_type':'ACCOUNT OPPENING (PMJDY)','sub_category':'CM003 - With e-KYC: initial deposit >= Rs 100 to < Rs 500','rate':30.0,'rate_type':'FIXED','min_amount':100.0,'max_amount':500.0,'max_exclusive':True,'min_exclusive':False,'allowed_months':'','kyc_requirement':'EKYC','rule_status':'CONFIRMED','commercial_scope':'TRANSACTION','priority':100,'source':'User-supplied SBI commission rule screenshot'},
        {'rule_id':'CM004','transaction_type':'ACCOUNT OPPENING (PMJDY)','sub_category':'CM004 - With e-KYC: initial deposit < Rs 100 (including zero balance)','rate':20.0,'rate_type':'FIXED','min_amount':pd.NA,'max_amount':100.0,'max_exclusive':True,'min_exclusive':False,'allowed_months':'','kyc_requirement':'EKYC','rule_status':'CONFIRMED','commercial_scope':'TRANSACTION','priority':100,'source':'User-supplied SBI commission rule screenshot'},
        {'rule_id':'CM005','transaction_type':'ACCOUNT OPPENING (PMJDY)','sub_category':'CM005 - Without e-KYC (with OVD): initial deposit >= Rs 100','rate':10.0,'rate_type':'FIXED','min_amount':100.0,'max_amount':pd.NA,'max_exclusive':False,'min_exclusive':False,'allowed_months':'','kyc_requirement':'OVD','rule_status':'CONFIRMED','commercial_scope':'TRANSACTION','priority':100,'source':'User-supplied SBI commission rule screenshot'},
        {'rule_id':'CM006','transaction_type':'ACCOUNT OPPENING (PMJDY)','sub_category':'CM006 - Without e-KYC (with OVD): initial deposit < Rs 100 (including zero balance)','rate':5.0,'rate_type':'FIXED','min_amount':pd.NA,'max_amount':100.0,'max_exclusive':True,'min_exclusive':False,'allowed_months':'','kyc_requirement':'OVD','rule_status':'CONFIRMED','commercial_scope':'TRANSACTION','priority':100,'source':'User-supplied SBI commission rule screenshot'},
        {'rule_id':'CM026','transaction_type':'PMJJBY','sub_category':'CM002 - Q1 (June-July-August) - premium Rs 436','rate':30.0,'rate_type':'FIXED','min_amount':436.0,'max_amount':436.0,'max_exclusive':False,'min_exclusive':False,'allowed_months':'6,7,8','rule_status':'CONFIRMED','commercial_scope':'TRANSACTION','priority':100,'source':'User-supplied SBI commission rule screenshot'},
        {'rule_id':'CM027','transaction_type':'PMJJBY','sub_category':'CM002 - Q2 (Sep-Oct-Nov) - premium Rs 342','rate':22.5,'rate_type':'FIXED','min_amount':342.0,'max_amount':342.0,'max_exclusive':False,'min_exclusive':False,'allowed_months':'9,10,11','rule_status':'CONFIRMED','commercial_scope':'TRANSACTION','priority':100,'source':'User-supplied SBI commission rule screenshot'},
        {'rule_id':'CM028','transaction_type':'PMJJBY','sub_category':'CM002 - Q3 (Dec-Jan-Feb) - premium Rs 228','rate':15.0,'rate_type':'FIXED','min_amount':228.0,'max_amount':228.0,'max_exclusive':False,'min_exclusive':False,'allowed_months':'12,1,2','rule_status':'CONFIRMED','commercial_scope':'TRANSACTION','priority':100,'source':'User-supplied SBI commission rule screenshot'},
        {'rule_id':'CM029','transaction_type':'PMJJBY','sub_category':'CM002 - Q4 (March-Apr-May) - premium Rs 114','rate':7.5,'rate_type':'FIXED','min_amount':114.0,'max_amount':114.0,'max_exclusive':False,'min_exclusive':False,'allowed_months':'3,4,5','rule_status':'CONFIRMED','commercial_scope':'TRANSACTION','priority':100,'source':'User-supplied SBI commission rule screenshot'},
        {'rule_id':'CM030','transaction_type':'PMSBY','sub_category':'CM003 - Age 18-70, cover Rs 2 lakh, premium Rs 20 per year','rate':1.0,'rate_type':'FIXED','min_amount':20.0,'max_amount':20.0,'max_exclusive':False,'min_exclusive':False,'allowed_months':'','rule_status':'CONFIRMED','commercial_scope':'TRANSACTION','priority':100,'source':'User-supplied SBI commission rule screenshot'},
    ])
    # These product rules are explicit in the supplied source, so replace older
    # copies rather than allowing duplicate same-priority rules to become ambiguous.
    ovd_account_rules = rules_df['transaction_type'].eq('ACCOUNT OPPENING (PMJDY)') & rules_df.get('kyc_requirement', pd.Series('', index=rules_df.index)).fillna('').astype(str).str.upper().eq('OVD')
    rules_df = rules_df[~rules_df['transaction_type'].isin(['ACCOUNT OPPENING (PMJDY)','PMJJBY','PMSBY']) | ovd_account_rules].copy()
    for col in rules_df.columns:
        if col not in _user_product_rules.columns: _user_product_rules[col]=pd.NA
    for col in _user_product_rules.columns:
        if col not in rules_df.columns: rules_df[col]=pd.NA
    with _warnings.catch_warnings():
        _warnings.simplefilter('ignore', FutureWarning)
        rules_df = pd.concat([rules_df, _user_product_rules[rules_df.columns]], ignore_index=True)

    # V62.6.103: enforce the explicit ₹100 minimum printed in SBI schedule rows
    # 4, 5, 6.a and 6.b. The lower slab is percentage/min/max; higher slabs are
    # fixed amounts. Apply to both rural and urban rules, without guessing geography.
    rules_df['transaction_type'] = rules_df['transaction_type'].map(_canonical_commercial_type)
    low_slab_types = {'CASH WITHDRAWAL', 'CASH DEPOSIT', 'FUNDTRANSFER - NON HOME', 'FUNDTRANSFER - HOME'}
    for _idx, _rule in rules_df.iterrows():
        _typ = norm(_rule.get('transaction_type'))
        _rt = norm(_rule.get('rate_type'))
        _mx = _numeric_or_none(_rule.get('max_amount'))
        if _typ in low_slab_types and _rt in {'PERCENTAGE', 'PERCENT', 'PERCENTAGE_PLUS_FIXED'} and _mx is not None and abs(_mx - 10000.0) < 0.001:
            rules_df.at[_idx, 'min_amount'] = 100.0
            rules_df.at[_idx, 'sub_category'] = str(_rule.get('sub_category') or '') + ' | Min transaction amount ₹100 (SBI schedule screenshot)'
            rules_df.at[_idx, 'source'] = str(_rule.get('source') or '') + ' + user-supplied SBI schedule screenshot'
    rules_df['rate']=parse_numeric_series(rules_df['rate'])
    rules_df['min_amount']=parse_numeric_series(rules_df['min_amount'])
    rules_df['max_amount']=parse_numeric_series(rules_df['max_amount'])
    rules_df['cap']=parse_numeric_series(rules_df['cap'])
    rules_df['floor']=parse_numeric_series(rules_df['floor'])
    rules_df['priority']=parse_numeric_series(rules_df['priority']).fillna(0)
    # Keep transaction-calculation rows only when the commercial scope is eligible
    # and the value is numeric. Non-transactional incentives remain in the workbook
    # metadata but cannot be derived from transaction rows alone.
    # SBI_Expected_Commission_Rule.xlsx is the only authority for expected revenue (business
    # instruction 2026-10-29). A legacy rule whose rate exists only in an older Excel ("EXCEL
    # ONLY", e.g. Debit Card ONUS Rs 14 / OFFUS Rs 13) is kept for the audit trail but is no
    # longer executable: those transactions show "Rate Master Missing", never a guessed amount.
    excel_only=rules_df['rule_status'].fillna('').astype(str).str.upper().str.contains('EXCEL ONLY',regex=False)
    if excel_only.any():
        rules_df.loc[excel_only,'rule_status']='NOT IN SBI MASTER - EXCEL ONLY'
        rules_df.loc[excel_only,'remarks']=rules_df.loc[excel_only,'remarks'].fillna('').astype(str)+' | Rate not present in SBI_Expected_Commission_Rule.xlsx; not used for expected revenue.'
    status_norm=rules_df['rule_status'].fillna('').astype(str).str.upper().str.strip()
    # Product-level mappings marked "Mapping to confirm" in the supplied SBI
    # workbook are deterministic rate mappings (the workbook explicitly says the
    # Excel product is mapped to the corresponding generic PDF schedule). They are
    # therefore calculable for control purposes, but the rule status is preserved so
    # the reconciliation engine can block final settlement until the mapping is
    # formally approved. Other unresolved statuses (To confirm / Value missing)
    # remain non-executable.
    executable=status_norm.str.startswith('CONFIRMED') | status_norm.eq('MAPPING TO CONFIRM')
    calc_rows=rules_df[rules_df['commercial_scope'].eq('TRANSACTION') & rules_df['rate'].notna() & executable].copy()
    warnings=list(unresolved)
    pending=int((rules_df['rule_status'].eq('MAPPING TO CONFIRM') & rules_df['commercial_scope'].eq('TRANSACTION')).sum())
    blocked=int((~executable & rules_df['commercial_scope'].eq('TRANSACTION')).sum())
    if pending: warnings.append(f'{pending} transaction rule row(s) are calculable but marked Mapping to confirm; they are provisional and cannot be used for final settlement.')
    if blocked: warnings.append(f'{blocked} transaction rule row(s) remain blocked because their source status is unresolved (To confirm / Value missing / other).')
    # Run the generic rule-table audit over the executable subset too, so
    # overlapping same-priority amount slabs are surfaced at upload time rather
    # than discovered only after a transaction is calculated.
    _, overlap_audit = validate_rate_master(calc_rows)
    overlap_warnings=[w for w in overlap_audit.get('warnings',[]) if 'Overlapping amount slabs' in str(w)]
    warnings.extend(w for w in overlap_warnings if w not in warnings)
    return calc_rows.reset_index(drop=True), {
        'valid':len(rules_df)>0,
        'rows':len(primary_rows),
        'rules':len(rules_df),
        'transaction_rules':len(calc_rows),
        'pending_rules':pending,
        'missing_columns':[],
        'errors':[],
        'warnings':warnings,
        'selected_sheet':primary_name,
        'available_sheets':sheets,
        'source_workbook_type':'SBI structured commission/slab master',
        'overlapping_slab_pairs': overlap_audit.get('overlapping_slab_pairs',0),
    }
