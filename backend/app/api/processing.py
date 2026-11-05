from pathlib import Path
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from app.services.transaction_processor import get_successful_transactions
from app.services.reconciliation_engine import TYPE_MAPPING, norm, map_transaction, resolve_transaction_type, build_reference_type_map
from app.services.upload_metadata import load_metadata
from app.services.processing_snapshot import load_snapshot

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parents[1]
TX = BASE_DIR / 'data' / 'transactions' / 'latest_transactions.csv'
CM = BASE_DIR / 'data' / 'commissions' / 'latest_commission.csv'
RM = BASE_DIR / 'data' / 'rate_master' / 'latest_rate_master.csv'

@router.get('/summary')
def processing_summary():
    snap=load_snapshot()
    if snap is None:
        raise HTTPException(400, 'Upload and validate the transaction file first.')
    return snap

@router.get('/mapping')
def processing_mapping():
    snap=load_snapshot()
    if snap is None:
        raise HTTPException(400, 'Upload and validate the transaction file first.')
    # Mapping counts are stored as a compact breakdown; no 300k-row CSV reread.
    refs=[]
    for p in (CM,RM):
        if p.exists():
            try: refs.append(pd.read_csv(p,low_memory=False))
            except Exception: pass
    ref_map=build_reference_type_map(*refs)
    rows=[]
    mapping_breakdown=snap.get('transaction_type_mapping_breakdown') or {}
    for t,n in (snap.get('transaction_type_breakdown') or {}).items():
        mapped_counts=mapping_breakdown.get(t) or {}
        mapped_total=sum(int(v) for v in mapped_counts.values())
        unmapped=max(int(n)-mapped_total,0)
        # Some source types (for example Initial deposit and Customer enroll for SSS)
        # intentionally map by transaction amount, so one raw type can resolve to
        # multiple approved commercial categories. Never map those rows using amount=0.
        if unmapped==0 and len(mapped_counts)==1:
            mapped_type=next(iter(mapped_counts))
            status='Mapped'
        elif unmapped==0 and len(mapped_counts)>1:
            mapped_type='; '.join(f'{k} ({v})' for k,v in sorted(mapped_counts.items()))
            status='Mapped - Amount Based'
        elif mapped_total>0:
            mapped_type='; '.join(f'{k} ({v})' for k,v in sorted(mapped_counts.items())) or None
            status='Partially Mapped'
        else:
            mapped_type=None; status='Unmapped'
        rows.append({'transaction_type_normalized':t,'successful_transactions':n,'commission_type':mapped_type,'mapping_status':status,'mapped_rows':mapped_total,'unmapped_rows':unmapped})
    return rows
