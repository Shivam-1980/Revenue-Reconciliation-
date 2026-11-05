"""Persist lightweight transaction-processing facts so the UI never rereads 300k rows just to render a page."""
import json
from pathlib import Path
import pandas as pd
from .reconciliation_engine import TYPE_MAPPING, norm, map_transaction, resolve_transaction_type, build_reference_type_map, load_transaction_mapping_master, canonical_key, ACCOUNT_OPEN_TYPES
from .number_parser import parse_date_series
from .transaction_processor import SUCCESS_STATUSES
from .fast_text import stripped, stripped_upper, on_unique
from pathlib import Path

BASE_DIR=Path(__file__).resolve().parents[1]
PATH=BASE_DIR/'data'/'transactions'/'processing_snapshot.json'
CM_PATH=BASE_DIR/'data'/'commissions'/'latest_commission.csv'
RM_PATH=BASE_DIR/'data'/'rate_master'/'latest_rate_master.csv'

def build_snapshot(df, source_meta=None):
    total=len(df)
    status=on_unique(df.get('status',pd.Series('',index=df.index)).astype('string').fillna(''), lambda x: x.str.strip().str.upper())
    success_mask=status.isin(SUCCESS_STATUSES)
    ref=df.get('transaction_id',pd.Series('',index=df.index)).astype('string').str.strip()
    csp_raw=stripped(df.get('csp_id',pd.Series('',index=df.index)))
    typ_raw=stripped(df.get('transaction_type',pd.Series('',index=df.index)))
    amt_raw=pd.to_numeric(df.get('amount',pd.Series(index=df.index)),errors='coerce')
    date_raw=df.get('transaction_date',pd.Series(pd.NaT,index=df.index))
    date_ok=parse_date_series(date_raw).notna()
    valid_fields=amt_raw.notna() & ref.notna() & ref.ne('') & csp_raw.notna() & csp_raw.ne('') & typ_raw.notna() & typ_raw.ne('') & date_ok
    eligible_success_mask=success_mask & valid_fields
    s=df.loc[eligible_success_mask].copy()
    if s.empty:
        return {'total_uploaded_rows':int(total),'successful_rows':0,'non_successful_rows':int(total),'success_rate':0,'transaction_amount':0,'invalid_amount_rows':0,'duplicate_reference_rows':0,'missing_csp_rows':0,'missing_transaction_type_rows':0,'unmapped_transaction_type_rows':0,'unique_csps':0,'unique_transaction_types':0,'mapped_transaction_type_rows':0,'mapped_transaction_type_rate':0,'status_breakdown':status.value_counts().head(10).to_dict(),'transaction_type_breakdown':{ },'transaction_type_mapping_breakdown':{},'source_file':source_meta}
    csp=on_unique(s['csp_id'].astype('string').fillna(''), lambda x: x.str.strip().str.upper())
    typ=on_unique(s['transaction_type'].astype('string').fillna(''), lambda x: x.map(norm))
    amt=pd.to_numeric(s.get('amount'),errors='coerce')
    # Deterministic exact mapping against the current uploaded commercial/report vocabularies.
    refs=[]
    if CM_PATH.exists():
        try: refs.append(pd.read_csv(CM_PATH,low_memory=False))
        except Exception: pass
    if RM_PATH.exists():
        try: refs.append(pd.read_csv(RM_PATH,low_memory=False))
        except Exception: pass
    ref_map=build_reference_type_map(*refs)
    # Vectorized deterministic mapping. The previous row-by-row resolver called
    # the mapping-master loader for every transaction, which made a 300k-row
    # upload unnecessarily expensive. Normal mappings are a direct Series.map;
    # only the two amount-sensitive classifications use small vectorized masks.
    mapping=load_transaction_mapping_master()
    mapped=typ.map(mapping).astype('object')

    # Exact uploaded reference vocabulary is allowed after approved operational
    # mapping, but never fuzzy matching.
    unresolved=mapped.isna()
    if unresolved.any() and ref_map:
        canonical=typ.loc[unresolved].map(canonical_key)
        mapped.loc[unresolved]=canonical.map(ref_map).to_numpy()

    # Initial deposit is split into the four approved BC account-opening buckets.
    initial=typ.eq('INITIAL DEPOSIT')
    if initial.any():
        a=pd.to_numeric(amt,errors='coerce')
        bucket=pd.Series(pd.NA,index=s.index,dtype='object')
        bucket.loc[initial & a.lt(100)]=ACCOUNT_OPEN_TYPES['BELOW']
        bucket.loc[initial & a.ge(100) & a.lt(500)]=ACCOUNT_OPEN_TYPES['100_499']
        bucket.loc[initial & a.ge(500) & a.lt(1000)]=ACCOUNT_OPEN_TYPES['500_999']
        bucket.loc[initial & a.ge(1000)]=ACCOUNT_OPEN_TYPES['1000_PLUS']
        parent_ref=ref_map.get(canonical_key('ACCOUNT OPPENING (PMJDY)'))
        for k in ACCOUNT_OPEN_TYPES.values():
            ck=canonical_key(k)
            replacement=ref_map.get(ck) or parent_ref or k
            bucket=bucket.replace(k,replacement)
        mapped.loc[initial]=bucket.loc[initial]

    # Social-security enrollment uses the documented premium values. Month-aware
    # eligibility is not inferred here; the processing snapshot only classifies
    # the product when the premium amount is deterministic.
    sss=typ.eq('CUSTOMER ENROLL FOR SSS')
    if sss.any():
        a=pd.to_numeric(amt,errors='coerce')
        sss_mapped=pd.Series(pd.NA,index=s.index,dtype='object')
        sss_mapped.loc[sss & a.sub(20).abs().lt(0.005)]=ref_map.get(canonical_key('PMSBY'),'PMSBY')
        pmjj=sss & ~sss_mapped.notna() & a.isin([436,342,228,114])
        sss_mapped.loc[pmjj]=ref_map.get(canonical_key('PMJJBY'),'PMJJBY')
        mapped.loc[sss]=sss_mapped.loc[sss]

    blank=lambda x: x.eq('').sum()
    refs=ref[eligible_success_mask].fillna('') if 'transaction_id' in s else pd.Series('',index=s.index)      # ref is the same strip, computed above
    mapping_frame=s.assign(_t=typ,_mapped=mapped.astype('string').fillna(''))
    mapping_breakdown={}
    for raw,grp in mapping_frame.groupby('_t',dropna=False):
        vals=grp['_mapped'].replace('',pd.NA).dropna().value_counts().to_dict()
        mapping_breakdown[str(raw)]=vals
    snap={'total_uploaded_rows':int(total),'successful_rows':int(len(s)),'non_successful_rows':int(total-int(success_mask.sum())),'invalid_success_rows':int((success_mask & ~valid_fields).sum()),'success_rate':round(len(s)/total*100,2) if total else 0,
          'transaction_amount':round(float(amt.fillna(0).sum()),2),'invalid_amount_rows':int(amt.isna().sum()),
          'duplicate_reference_rows':int(refs[refs.ne('')].duplicated(keep=False).sum()),'missing_csp_rows':int(csp.isin({'','NAN','NONE'}).sum()),
          'missing_transaction_type_rows':int(typ.eq('').sum()),'unmapped_transaction_type_rows':int(mapped.isna().sum()),
          'unique_csps':int(csp.replace({'','NAN','NONE'},pd.NA).nunique(dropna=True)),'unique_transaction_types':int(typ.replace('',pd.NA).nunique(dropna=True)),
          'mapped_transaction_type_rows':int(mapped.notna().sum()),'mapped_transaction_type_rate':round(mapped.notna().mean()*100,2),
          'status_breakdown':status.value_counts().head(10).to_dict(),'transaction_type_breakdown':s.assign(_t=typ).groupby('_t').size().sort_values(ascending=False).head(30).to_dict(),
          'transaction_type_mapping_breakdown':mapping_breakdown,'source_file':source_meta}
    return snap

def save_snapshot(snapshot):
    PATH.parent.mkdir(parents=True,exist_ok=True); PATH.write_text(json.dumps(snapshot,default=str),encoding='utf-8')

def load_snapshot():
    if not PATH.exists(): return None
    try:return json.loads(PATH.read_text(encoding='utf-8'))
    except Exception:return None
