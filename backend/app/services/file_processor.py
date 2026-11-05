from io import BytesIO
from typing import Optional
import pandas as pd
from app.services import excel_io
from openpyxl import load_workbook
import re, zipfile, xml.etree.ElementTree as ET

TRANSACTION_HINTS={"reference_number","type_of_transaction","amount","status"}
COMMISSION_HINTS={"csp_code","transaction_type","commission"}
RATE_MASTER_HINTS={
"transaction_type","txn_type","commission_type","rate_type","rate","commission","commission_rate","commission_amount",
"commission_per_transaction","commission_per_txn","commission_per_enrollment","commission_value","payout","payout_rate",
"product","product_name","product_service","product_type","service","service_name","component","component_name",
"slab","slab_min","slab_max","slab_range","slab_from","slab_to","min_amount","max_amount","amount_from","amount_to",
"effective_date","effective_from","valid_from","start_date","from_date","fixed_fee","fixed_amount",
"avg_per_enrollment_revenue","avg_revenue_per_enrollment","enrollment_type","sub_category","sub_category_rule","commission_cycle",
"percentage","percent","rate_value","commission_rs","commission_inr","fee","fee_amount","remuneration","incentive"
}
MAIN_NS="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS="http://schemas.openxmlformats.org/package/2006/relationships"

def normalize_columns(df):
    result=df.copy(); result.columns=(result.columns.astype(str).str.strip().str.lower().str.replace(r"[^a-z0-9]+","_",regex=True).str.strip("_")); return result

def clean_string_columns(df):
    return df

def _norm_sheet(name): return " ".join(str(name).strip().lower().replace("_"," ").replace("-"," ").split())
def _score(vals,hints):
    """Score a possible header row for source spreadsheets.

    Rate masters in banking operations are often human-formatted and use labels
    such as ``Product/Service``, ``Commission (Rs.)`` or ``Commission per
    Enrollment``. Exact-column matching alone rejects these perfectly valid
    masters. Score normalized aliases and semantic tokens instead, while still
    requiring at least two meaningful fields before accepting a header.
    """
    cols=set(normalize_columns(pd.DataFrame(columns=[str(v) for v in vals])).columns)
    score=len(cols.intersection(hints))
    # Semantic aliases which normalize differently from the canonical names.
    aliases={
        "product_service":"product", "product_or_service":"product", "product_service_name":"product",
        "commission_rs":"commission", "commission_inr":"commission", "commission_rupees":"commission",
        "commission_per_transaction":"commission", "commission_per_txn":"commission",
        "commission_per_enrollment":"commission", "commission_amount":"commission", "commission_value":"commission",
        "payout":"commission", "payout_rate":"rate", "fee_amount":"commission", "remuneration":"commission",
        "slab_range":"slab", "slab_from":"slab", "slab_to":"slab", "rate_value":"rate",
        "percentage":"rate", "percent":"rate", "fixed_amount":"fixed_fee", "amount_from":"min_amount", "amount_to":"max_amount",
    }
    score += sum(1 for c in cols if c in aliases and aliases[c] in hints)
    # Distinct semantic groups are more important than repeated commission words.
    groups=0
    if any(c in cols for c in {"transaction_type","txn_type","commission_type","product","product_name","product_service","product_or_service","service","service_name","component"}): groups+=1
    if any(c in cols for c in {"rate","commission","commission_rate","commission_amount","commission_rs","commission_inr","commission_per_transaction","commission_per_enrollment","fixed_fee","fixed_amount","payout","percentage","percent"}): groups+=1
    if any(c in cols for c in {"rate_type","calculation_type","basis","effective_date","effective_from","valid_from","start_date","from_date","slab","slab_range","min_amount","max_amount"}): groups+=1
    return score + (1 if groups>=2 else 0)
def _header_from_openpyxl(ws,hints,max_rows=200):
    best=(-1,0)
    for i,row in enumerate(ws.iter_rows(min_row=1,max_row=max_rows,values_only=True)):
        vals=[v for v in row if v is not None and str(v).strip()]; score=_score(vals,hints)
        if score>best[0]: best=(score,i)
    return best

def _choose_sheet(wb,sheets,hints,kind):
    normalized={_norm_sheet(s):s for s in sheets}; preferred=[]
    if kind=="transactions": preferred=["success","successful transactions","successful transaction"]
    elif kind=="commission": preferred=["csp wise transaction type wise","csp wise transaction type"]
    for target in preferred:
        if target in normalized:
            ws=wb[normalized[target]]; score,row=_header_from_openpyxl(ws,hints)
            if score>=2:return normalized[target],score,row
    candidates=[]
    for sheet in sheets:
        score,row=_header_from_openpyxl(wb[sheet],hints); candidates.append((score,sheet,row))
    candidates.sort(reverse=True,key=lambda x:x[0]); return candidates[0][1],candidates[0][0],candidates[0][2]

def _col_index(ref):
    n=0
    for ch in ref:
        if ch.isalpha(): n=n*26+(ord(ch.upper())-64)
        else: break
    return n-1

def _xlsx_metadata(z):
    root=ET.fromstring(z.read('xl/workbook.xml'))
    relroot=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    relmap={r.attrib['Id']:r.attrib['Target'] for r in relroot}
    sheets=[]
    for s in root.find(f'{{{MAIN_NS}}}sheets'):
        rid=s.attrib.get(f'{{{REL_NS}}}id'); target=relmap.get(rid,'')
        if target.startswith('/'): path=target.lstrip('/')
        else: path='xl/'+target.lstrip('/') if not target.startswith('xl/') else target
        sheets.append((s.attrib['name'],path))
    return sheets


def _shared_strings(z):
    name='xl/sharedStrings.xml'
    if name not in z.namelist(): return []
    out=[]; tag_si=f'{{{MAIN_NS}}}si'; tag_t=f'{{{MAIN_NS}}}t'
    with z.open(name) as f:
        for _,e in ET.iterparse(f,events=('end',)):
            if e.tag==tag_si:
                out.append(''.join(t.text or '' for t in e.iter(tag_t))); e.clear()
    return out

def _cell_value(c,shared):
    typ=c.attrib.get('t'); v=c.find(f'{{{MAIN_NS}}}v')
    if typ=='inlineStr':
        return ''.join(t.text or '' for t in c.iter(f'{{{MAIN_NS}}}t'))
    if v is None: return ''
    val=v.text or ''
    if typ=='s':
        try:return shared[int(val)]
        except Exception:return val
    if typ=='b': return '1' if val=='1' else '0'
    return val

# --- Fast worksheet scanner (V62.6.209; moved to app/xlsx_scan.py and parallelised in V62.6.214) -----------------
# Same rows/strings as the ElementTree parser below, several times faster; big sheets are scanned on several CPU
# cores. Anything the scanner does not fully understand makes it hand the sheet to ElementTree.
import logging as _logging
from app import xlsx_scan

_FastParseUnsupported = xlsx_scan.FastParseUnsupported
_xml_text = xlsx_scan.xml_text
_log = _logging.getLogger("eko.xlsx")


def _parse_sheet_xml_fast(xml,shared,max_rows=None):
    rows,max_col=xlsx_scan.scan(xml,shared,max_rows)
    return xlsx_scan.dense(rows,max_col+1)


def _shared_strings_fast(z):
    name='xl/sharedStrings.xml'
    if name not in z.namelist(): return []
    return xlsx_scan.shared_strings(z.read(name).decode('utf-8'))


def _parse_sheet_xml(z,path,shared,max_rows=None):
    """Read an XLSX worksheet without silently dropping physical rows/cells (fast scanner first)."""
    try:
        with z.open(path) as f:
            data=f.read(4*1024*1024) if max_rows else f.read()
        if max_rows and b'</sheetData>' not in data:
            # Header scan reads a 4 MB prefix; cut it (in bytes) after the last complete row.
            cut=data.rfind(b'</row>')
            if cut<0: raise _FastParseUnsupported()
            data=data[:cut+len(b'</row>')]
        text=data.decode('utf-8')
        if not max_rows and xlsx_scan.parallel_available(len(data)):
            try:
                return xlsx_scan.parse_parallel(text,shared)
            except Exception as exc:     # any problem with worker processes: use the single-process scanner
                _log.warning("Parallel XLSX scan unavailable (%s: %s); scanning in one process", type(exc).__name__, exc)
                xlsx_scan.shutdown_pool()
        return _parse_sheet_xml_fast(text,shared,max_rows)
    except (_FastParseUnsupported, UnicodeDecodeError):
        return _parse_sheet_xml_et(z,path,shared,max_rows)


def _parse_sheet_xml_et(z,path,shared,max_rows=None):
    """Read an XLSX worksheet without silently dropping physical rows/cells.

    The parser keeps sparse cells and blank header cells. The caller decides which
    rows are actual data. max_rows is used only for header detection.
    """
    tag_row=f'{{{MAIN_NS}}}row'; tag_c=f'{{{MAIN_NS}}}c'
    rows=[]; sheet_max_col=-1
    with z.open(path) as f:
        for _,e in ET.iterparse(f,events=('end',)):
            if e.tag != tag_row: continue
            row={}
            for c in e.findall(tag_c):
                idx=_col_index(c.attrib.get('r','A1')); sheet_max_col=max(sheet_max_col,idx)
                row[idx]=_cell_value(c,shared)
            rows.append(row)
            e.clear()
            if max_rows and len(rows)>=max_rows: break
    width=sheet_max_col+1
    dense=[]
    for row in rows:
        dense.append([row.get(i) for i in range(width)])
    return dense

def _fast_xlsx_read(content,kind,sheet_name=None):
    with zipfile.ZipFile(BytesIO(content)) as z:
        sheet_meta=_xlsx_metadata(z); sheets=[x[0] for x in sheet_meta]
        try: shared=_shared_strings_fast(z)
        except (_FastParseUnsupported, UnicodeDecodeError): shared=_shared_strings(z)
        hints=TRANSACTION_HINTS if kind=='transactions' else (COMMISSION_HINTS if kind=='commission' else RATE_MASTER_HINTS)
        if sheet_name:
            matches=[x for x in sheet_meta if x[0]==sheet_name]
            if not matches: raise ValueError(f"Sheet '{sheet_name}' not found. Available sheets: {', '.join(sheets)}")
            chosen,path=matches[0]; headrows=_parse_sheet_xml(z,path,shared,max_rows=200); scores=[(_score(r,hints),i) for i,r in enumerate(headrows)]; score,row=max(scores,key=lambda x:x[0],default=(-1,0))
        else:
            preferred=[]
            if kind=='transactions': preferred=['success','successful transactions','successful transaction']
            elif kind=='commission': preferred=['csp wise transaction type wise','csp wise transaction type']
            normalized={_norm_sheet(s): (s,p) for s,p in sheet_meta}
            candidate=None
            for target in preferred:
                if target in normalized:
                    s,p=normalized[target]; hr=_parse_sheet_xml(z,p,shared,max_rows=200); score,row=max(((_score(r,hints),i) for i,r in enumerate(hr)),default=(-1,0))
                    if score>=2: candidate=(s,p,score,row); break
            if candidate: chosen,path,score,row=candidate
            else:
                cand=[]
                for s,p in sheet_meta:
                    hr=_parse_sheet_xml(z,p,shared,max_rows=200); sc,ri=max(((_score(r,hints),i) for i,r in enumerate(hr)),default=(-1,0)); cand.append((sc,s,p,ri))
                score,chosen,path,row=max(cand,key=lambda x:x[0])
        minimum=2
        if score<minimum: raise ValueError(f"Could not detect the {'rate/slab master' if kind=='rate_master' else 'source-data'} header in worksheet '{chosen}'.")
        allrows=_parse_sheet_xml(z,path,shared,max_rows=None)
        if not allrows: return pd.DataFrame(),chosen,sheets,row
        header_row=allrows[row]
        # Never truncate cells that exist to the right of the detected header.
        width=max(len(header_row), max((len(r) for r in allrows), default=0))
        headers=[]
        used=set()
        for i in range(width):
            raw=header_row[i] if i < len(header_row) else None
            h=str(raw).strip() if raw is not None and str(raw).strip() else f'__source_col_{i+1}'
            base=h; n=2
            while h in used:
                h=f'{base}_{n}'; n+=1
            used.add(h); headers.append(h)
        data=[]; blank_rows=0
        for r in allrows[row+1:]:
            vals=(r+[None]*width)[:width]
            if all(v is None or str(v).strip()=='' for v in vals):
                blank_rows += 1
                continue
            data.append(vals)
        df=pd.DataFrame(data,columns=headers)
        df.attrs['source_physical_rows_after_header']=len(allrows)-row-1
        df.attrs['blank_rows_after_header']=blank_rows
        df.attrs['source_nonblank_rows']=len(data)
        df.attrs['source_column_count']=width
        df.attrs['source_sheet']=chosen
        df.attrs['source_header_row_zero_based']=row
        return df,chosen,sheets,row

def read_uploaded_file(filename,content,sheet_name=None,kind=None):
    name=filename.lower()
    if name.endswith('.csv'):
        try: df=pd.read_csv(BytesIO(content),encoding='utf-8-sig',low_memory=False)
        except UnicodeDecodeError: df=pd.read_csv(BytesIO(content),encoding='latin-1',low_memory=False)
        return df,None,[],None
    if not name.endswith('.xlsx'): raise ValueError('Unsupported file type. Upload only CSV or XLSX.')
    # Fast XML reader is preferred for large XLSX uploads; it avoids openpyxl's
    # expensive workbook object construction. Fall back to openpyxl for unusual files.
    try: return _fast_xlsx_read(content,kind,sheet_name)
    except Exception:
        wb=load_workbook(BytesIO(content),read_only=True,data_only=True); sheets=wb.sheetnames
        hints=TRANSACTION_HINTS if kind=='transactions' else (COMMISSION_HINTS if kind=='commission' else RATE_MASTER_HINTS)
        if sheet_name:
            if sheet_name not in sheets: wb.close(); raise ValueError(f"Sheet '{sheet_name}' not found. Available sheets: {', '.join(sheets)}")
            chosen=sheet_name; score,row=_header_from_openpyxl(wb[chosen],hints)
        else: chosen,score,row=_choose_sheet(wb,sheets,hints,kind)
        if score<2: wb.close(); raise ValueError(f"Could not detect the source-data header in worksheet '{chosen}'.")
        df=excel_io.read_excel(content,sheet_name=chosen,header=row,engine='openpyxl'); wb.close(); return df,chosen,sheets,row

def get_excel_sheet_names(filename,content):
    if not filename.lower().endswith('.xlsx'): return []
    try:
        with zipfile.ZipFile(BytesIO(content)) as z: return [x[0] for x in _xlsx_metadata(z)]
    except Exception:
        wb=load_workbook(BytesIO(content),read_only=True,data_only=True); sheets=wb.sheetnames; wb.close(); return sheets

def preview_dataframe(df,limit=10):
    x=df.head(limit).where(pd.notnull(df.head(limit)),None); return x.to_dict(orient='records')
