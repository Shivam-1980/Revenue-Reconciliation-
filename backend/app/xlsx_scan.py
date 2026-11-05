"""Fast XLSX worksheet scanner (V62.6.214). Pure ``re`` so worker processes start in milliseconds.

``scan(xml, shared)`` returns the cells of ``<row>`` elements exactly as the ElementTree parser in
file_processor does (same strings, same sparse/blank cells). With ``shared=None`` a shared-string cell comes back
as its integer index, so the strings need not be shipped to worker processes; the caller resolves them.

``parse_parallel`` splits a big sheet at ``</row>`` boundaries and scans the parts on several CPU cores.
Anything unusual raises FastParseUnsupported and the caller falls back to the slower, fully general parser.
"""
from __future__ import annotations

import atexit
import os
import re

_T_RE = re.compile(r'<t(?:\s[^>]*)?(?:/>|>(.*?)</t>)', re.S)
_SI_RE = re.compile(r'<si\b[^>]*?(?:/>|>(.*?)</si>)', re.S)
_V_RE = re.compile(r'<v(?:\s[^>]*)?(?:/>|>(.*?)</v>)', re.S)
_UNSUPPORTED_RE = re.compile(r"<\w+:(?:row|c|v|t|si|sheetData)\b|<!\[CDATA\[|<c\b[^>]*='")
_ENTITY_RE = re.compile(r'&(#x[0-9A-Fa-f]+|#[0-9]+|amp|lt|gt|quot|apos);')
_NAMED_ENTITIES = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'"}
# Cells must use Excel's usual attribute order (r, then optional s, then optional t); a part whose <c>/<row> tag
# count differs from what was matched is not trusted.
_TOKEN_RE = re.compile(r'<row\b[^>]*?(/)?>|(</row>)|<c r="([A-Z]+)[0-9]+"(?: s="[0-9]+")?(?: t="([A-Za-z]+)")?(?:/>|>(.*?)</c>)', re.S)
_TAG_RE = re.compile(r'<(c|row)[\s/>]')
_CHUNK = 8 * 1024 * 1024
_COL_CACHE: dict = {}


class FastParseUnsupported(Exception):
    pass


def xml_text(raw):
    """Text exactly as an XML parser reports it: line endings normalised, then entities decoded."""
    if raw is None:
        return None
    if '\r' in raw:
        raw = raw.replace('\r\n', '\n').replace('\r', '\n')
    if '&' not in raw:
        return raw

    def sub(m):
        e = m.group(1)
        if e[0] == '#':
            return chr(int(e[2:], 16) if e[1] in 'xX' else int(e[1:]))
        return _NAMED_ENTITIES[e]
    return _ENTITY_RE.sub(sub, raw)


def col_index(letters):
    idx = _COL_CACHE.get(letters)
    if idx is None:
        n = 0
        for ch in letters:
            n = n * 26 + (ord(ch.upper()) - 64)
        idx = _COL_CACHE[letters] = n - 1
    return idx


def value_from_body(typ, body, shared):
    if typ == 'inlineStr':
        if body.startswith('<is><t>') and body.endswith('</t></is>') and body.count('<') == 4:
            raw = body[7:-9]
            return xml_text(raw) if ('&' in raw or '\r' in raw) else raw
        return ''.join(xml_text(t) or '' for t in _T_RE.findall(body))
    if not body:
        return ''
    if body.startswith('<v>') and body.endswith('</v>') and body.count('<') == 2:
        raw = body[3:-4]
    else:
        vm = _V_RE.search(body)
        if vm is None:
            return ''
        raw = vm.group(1) or ''
    val = xml_text(raw) if ('&' in raw or '\r' in raw) else raw
    if typ == 's':
        try:
            return int(val) if shared is None else shared[int(val)]
        except Exception:
            return val
    if typ == 'b':
        return '1' if val == '1' else '0'
    return val


def scan(xml: str, shared, max_rows=None, whole_sheet=True):
    """Return (rows as {column: value} dicts, highest column index). ``whole_sheet`` = xml still contains <sheetData>."""
    if _UNSUPPORTED_RE.search(xml):
        raise FastParseUnsupported()
    start = 0
    end = len(xml)
    if whole_sheet:
        start = xml.find('<sheetData')
        if start < 0:
            return [], -1
        found = xml.find('</sheetData>', start)
        end = len(xml) if found < 0 else found
    rows, row, sheet_max_col, cache, pos = [], None, -1, _COL_CACHE, start
    while pos < end:
        cut = end if end - pos <= _CHUNK else xml.find('</row>', pos + _CHUNK)
        cut = end if cut < 0 else min(end, cut + len('</row>'))
        chunk = xml[pos:cut]
        pos = cut
        tokens = _TOKEN_RE.findall(chunk)
        cells = sum(1 for t in tokens if t[2])
        tags = _TAG_RE.findall(chunk)
        c_tags = tags.count('c')
        if cells != c_tags or len(tokens) - cells - sum(1 for t in tokens if t[1]) != len(tags) - c_tags:
            raise FastParseUnsupported()
        for selfclose, rowclose, col, typ, body in tokens:
            if col:
                if row is None:
                    raise FastParseUnsupported()
                idx = cache.get(col)
                if idx is None:
                    idx = col_index(col)
                if idx > sheet_max_col:
                    sheet_max_col = idx
                row[idx] = value_from_body(typ, body, shared)
            elif rowclose or selfclose:
                rows.append(row if rowclose else {})
                row = None
                if max_rows and len(rows) >= max_rows:
                    pos = end
                    break
            else:
                row = {}
    return rows, sheet_max_col


def dense(rows, width, shared=None):
    out = [[r.get(i) for i in range(width)] for r in rows]
    if shared:
        out = [[shared[v] if v.__class__ is int else v for v in row] for row in out]
    return out


def shared_strings(xml: str) -> list:
    if _UNSUPPORTED_RE.search(xml):
        raise FastParseUnsupported()
    out = []
    for body in _SI_RE.findall(xml):
        if not body:
            out.append('')
        elif body.startswith('<t>') and body.endswith('</t>') and body.count('<') == 2:      # the usual plain string
            raw = body[3:-4]
            out.append(xml_text(raw) if ('&' in raw or '\r' in raw) else raw)
        else:
            out.append(''.join(xml_text(t) or '' for t in _T_RE.findall(body)))
    return out


# ------------------------------------------------------------------ parallel scan
def _scan_part(part: str):
    """Worker: scan one part and return dense rows (cheaper to send than dicts) with their width."""
    rows, max_col = scan(part, None, whole_sheet=False)
    width = max_col + 1
    return [[r.get(i) for i in range(width)] for r in rows], width


_pool = None


def _workers() -> int:
    wanted = os.getenv("EKO_XLSX_WORKERS", "").strip()
    return max(0, int(wanted)) if wanted.isdigit() else min(6, max(0, (os.cpu_count() or 1) - 2))


def _get_pool():
    global _pool
    if _pool is None:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        _pool = ProcessPoolExecutor(max_workers=_workers(), mp_context=multiprocessing.get_context("spawn"))
        atexit.register(shutdown_pool)
    return _pool


def shutdown_pool():
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


def warm_pool():
    """Start the worker processes ahead of the first big upload (they take ~0.3 s each, in parallel)."""
    if _workers() >= 2:
        list(_get_pool().map(len, [""] * _workers()))


def _main_is_importable() -> bool:
    """Windows 'spawn' workers re-import the parent's main script/module; if it has none (stdin, -c) stay single-process."""
    import sys
    main = sys.modules.get("__main__")
    if getattr(getattr(main, "__spec__", None), "name", None):
        return True
    path = getattr(main, "__file__", None)
    return bool(path) and os.path.isfile(path)


def parallel_available(size: int) -> bool:
    return (size >= int(os.getenv("EKO_XLSX_PARALLEL_MIN_BYTES", str(24 * 1024 * 1024))) and _workers() >= 2 and _main_is_importable())


def parse_parallel(xml: str, shared):
    """Scan a big worksheet on several cores; result identical to ``dense(*scan(xml, shared), shared)``."""
    head = xml[:65536]
    if _UNSUPPORTED_RE.search(head):
        raise FastParseUnsupported()
    start = xml.find('<sheetData')
    if start < 0:
        return []
    end = xml.find('</sheetData>', start)
    end = len(xml) if end < 0 else end
    parts_wanted = max(2, _workers() * 2)
    step = (end - start) // parts_wanted
    cuts = [start]
    for k in range(1, parts_wanted):
        c = xml.find('</row>', start + k * step)
        if c < 0 or c + 6 >= end:
            break
        c += len('</row>')
        if c > cuts[-1]:
            cuts.append(c)
    cuts.append(end)
    parts = [xml[a:b] for a, b in zip(cuts, cuts[1:]) if b > a]
    results = list(_get_pool().map(_scan_part, parts))
    width = max((w for _, w in results), default=0)
    rows = []
    for part_rows, part_width in results:
        if part_width < width:                       # a part with fewer columns than the widest one: pad like the single-process scan
            pad = [None] * (width - part_width)
            part_rows = [r + pad for r in part_rows]
        rows.extend(part_rows)
    if shared:
        rows = [[shared[v] if v.__class__ is int else v for v in row] for row in rows]
    return rows
