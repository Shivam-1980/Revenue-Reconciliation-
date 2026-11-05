from pathlib import Path
from typing import Optional
import math
import pandas as pd
from app.services import excel_io
from fastapi import APIRouter, HTTPException, Query
from app.services.upload_metadata import load_metadata

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parents[1]
TX = BASE_DIR / 'data' / 'transactions'
CM = BASE_DIR / 'data' / 'commissions'
EXPECTED_RULE = BASE_DIR / 'data' / 'expected_commission_rule' / 'latest.xlsx'

FILES = {
    'transactions': TX / 'latest_transactions_raw.csv',
    'commission': CM / 'latest_commission_raw.csv',
}
FALLBACK = {
    'transactions': TX / 'latest_transactions.csv',
    'commission': CM / 'latest_commission.csv',
}

def _safe(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if hasattr(v, 'item'):
        try:
            return _safe(v.item())
        except Exception:
            pass
    return v

def _header_token(value):
    import re
    if value is None or pd.isna(value):
        return ''
    return re.sub(r'[^a-z0-9]+', '', str(value).strip().lower().replace('\ufeff',''))

def _looks_like_header_row(row, columns):
    if len(row) != len(columns):
        return False
    matches = sum(_header_token(v) == _header_token(c) and _header_token(c) != '' for v, c in zip(row, columns))
    # Require every non-empty column to match. This catches duplicated Excel
    # headers even when spaces/BOM/punctuation differ.
    nonempty = sum(_header_token(c) != '' for c in columns)
    return nonempty > 0 and matches == nonempty

def _load(kind: str):
    path = FILES[kind] if FILES[kind].exists() else FALLBACK[kind]
    if not path.exists():
        raise HTTPException(404, f'No uploaded {kind} source is available yet.')
    try:
        df = pd.read_csv(path, low_memory=False)
        # Guard against an old cached/raw snapshot that accidentally retained the
        # Excel header as the first data row.  The source-data page must represent
        # data rows only; the header is metadata, never a transaction/commission row.
        meta = load_metadata().get(kind) or {}
        # Always strip a duplicated header-as-data row.  Do not gate this on
        # metadata because an older upload can itself contain the wrong row
        # count.  The source file's parsed data is authoritative for this view.
        if len(df) > 0 and _looks_like_header_row(df.iloc[0].tolist(), list(df.columns)):
            df = df.iloc[1:].reset_index(drop=True)
        return df
    except Exception as e:
        raise HTTPException(500, f'Unable to read stored {kind} source: {e}')

def _load_expected_rule_sheet(sheet_name: Optional[str] = None):
    if not EXPECTED_RULE.exists():
        raise HTTPException(404, 'No SBI Expected Commission Rule workbook has been uploaded yet.')
    try:
        xl = excel_io.excel_file(EXPECTED_RULE)
        chosen = sheet_name if sheet_name in xl.sheet_names else next((x for x in xl.sheet_names if x.strip().upper() == 'CONSOLIDATED COMMISSION MASTER'), xl.sheet_names[0])
        if chosen.strip().upper() == 'CONSOLIDATED COMMISSION MASTER':
            df = excel_io.read_excel(EXPECTED_RULE, sheet_name=chosen, header=3, engine='openpyxl').dropna(how='all').copy()
            # Remove rows with no meaningful rule component; keep all six rule fields.
            component_col = 'Component / Particulars'
            if component_col in df.columns:
                df = df[df[component_col].notna() & df[component_col].astype(str).str.strip().ne('')].copy()
            df = df.reset_index(drop=True)
            header_row = 3
        else:
            # Preserve the entire supporting matrix/audit sheet exactly as displayed,
            # including section titles and multi-table structure.
            raw = excel_io.read_excel(EXPECTED_RULE, sheet_name=chosen, header=None, engine='openpyxl')
            raw = raw.dropna(how='all').copy()
            raw = raw.reset_index(drop=True)
            raw.columns = [f'Column {chr(65+i)}' if i < 26 else f'Column {i+1}' for i in range(len(raw.columns))]
            df = raw
            header_row = None
        return df, chosen, xl.sheet_names, header_row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f'Unable to read SBI Expected Commission Rule workbook: {e}')


@router.get('/{kind}')
def source_data(
    kind: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    search: Optional[str] = Query(None),
    sheet_name: Optional[str] = Query(None),
):
    if kind == 'expected_commission_rule':
        df, chosen, available_sheets, header_row = _load_expected_rule_sheet(sheet_name)
        meta = load_metadata().get('expected_commission_rule') or {}
        total = len(df)
        if search and search.strip():
            term = search.strip().lower()
            mask = pd.Series(False, index=df.index)
            for col in df.columns:
                mask |= df[col].astype('string').fillna('').str.lower().str.contains(term, regex=False, na=False)
            view = df.loc[mask]
        else:
            view = df
        filtered_total = len(view)
        page = view.iloc[offset:offset + limit]
        rows = []
        for idx, row in page.iterrows():
            item = {'__row_number': int(idx) + (header_row + 2 if header_row is not None else 1)}
            for col, value in row.items(): item[str(col)] = _safe(value)
            rows.append(item)
        return {'kind':kind,'filename':meta.get('filename') or 'SBI_Expected_Commission_Rule.xlsx','sheet_name':chosen,
                'available_sheets':available_sheets,'period_start':None,'period_end':None,'uploaded_at':meta.get('uploaded_at'),
                'total_rows':total,'source_data_rows':total,'stored_source_data_rows':total,'filtered_rows':filtered_total,
                'offset':offset,'limit':limit,'columns':[str(c) for c in df.columns],'rows':rows,
                'validation':meta.get('validation') or {},'raw_source_available':EXPECTED_RULE.exists()}
    if kind not in FILES:
        raise HTTPException(404, 'Supported source types: transactions, commission, expected_commission_rule')
    df = _load(kind)
    # The source-data page must count the rows actually present in the parsed
    # source snapshot after removing any duplicated header row.  Metadata can be
    # stale or originate from an older parser, so it is never authoritative here.
    meta = load_metadata().get(kind) or {}
    total = len(df)
    if search and search.strip():
        term = search.strip().lower()
        mask = pd.Series(False, index=df.index)
        for col in df.columns:
            s = df[col].astype('string').fillna('')
            mask |= s.str.lower().str.contains(term, regex=False, na=False)
        view = df.loc[mask]
    else:
        view = df
    filtered_total = len(view)
    page = view.iloc[offset:offset + limit]
    rows = []
    for idx, row in page.iterrows():
        item = {'__row_number': int(idx) + 2}
        for col, value in row.items():
            item[str(col)] = _safe(value)
        rows.append(item)
    validation = meta.get('validation') or {}
    return {
        'kind': kind,
        'filename': meta.get('filename'),
        'sheet_name': meta.get('sheet_name'),
        'period_start': meta.get('period_start'),
        'period_end': meta.get('period_end'),
        'uploaded_at': meta.get('uploaded_at'),
        'total_rows': total,
        'source_data_rows': total,
        'stored_source_data_rows': meta.get('source_data_rows'),
        'filtered_rows': filtered_total,
        'offset': offset,
        'limit': limit,
        'columns': [str(c) for c in df.columns],
        'rows': rows,
        'validation': validation,
        'raw_source_available': FILES[kind].exists(),
    }
