"""The fast XLSX scanner must return exactly what the ElementTree parser returns."""
import datetime as dt
import io
import zipfile

import openpyxl
import pandas as pd
import pytest

from app.services import file_processor as fp


def _both(content, max_rows=None):
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        meta = fp._xlsx_metadata(z)
        shared_et = fp._shared_strings(z)
        shared_fast = fp._shared_strings_fast(z)
        assert shared_fast == shared_et
        out = []
        for _, path in meta:
            et = fp._parse_sheet_xml_et(z, path, shared_et, max_rows)
            fast = fp._parse_sheet_xml(z, path, shared_et, max_rows)
            out.append((et, fast))
        return out


def _workbook_bytes(build):
    wb = openpyxl.Workbook()
    build(wb)
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()


def _tricky(wb):
    ws = wb.active; ws.title = "Success"
    ws.append(["Monthly report — SBI & Eko <BC>"]); ws.append([])
    ws.append(["Reference Number", "CSP Code", "Type of Transaction", "Amount", "Date", "Status", None, "Notes"])
    ws.append([412345678901, "1A850001", "AEPS ONUS Withdrawal", 1000, dt.date(2026, 9, 10), "SUCCESS", None, 'quote " and \' apos'])
    ws.append(["R2", "1A850002", "Money Transfer", 1000.5, dt.datetime(2026, 9, 11, 14, 5), " SUCCESS ", "x", "line1\nline2\r\nline3"])
    ws.append([None] * 8)
    ws.append(["R3", "१२३ हिन्दी", "Fund Transfer", -0.01, "2026-09-12", "FAILED", True, "tab\there & amp"])
    ws.append(["R4", "1A850004", "Initial Deposit", 1e-7, dt.time(9, 30), "SUCCESS", False, "=SUM(1,2)"])
    ws["H8"] = "=1+1"
    ws.cell(row=9, column=12, value="far right cell")
    ws2 = wb.create_sheet("Second sheet")
    for i in range(500):
        ws2.append([f"ref-{i}", i * 1.25, f"CSP{i % 7}", "€ ✓ 😀" if i % 50 == 0 else ""])


def test_fast_scanner_matches_elementtree_on_tricky_workbook():
    content = _workbook_bytes(_tricky)
    for et, fast in _both(content):
        assert fast == et
    for et, fast in _both(content, max_rows=200):
        assert fast == et


def test_fast_scanner_matches_on_inline_strings_rich_text_and_entities():
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             '<row r="1"><c r="A1" t="inlineStr"><is><t>Reference Number</t></is></c><c r="B1" t="inlineStr"><is><r><t>CSP </t></r><r><t xml:space="preserve">Code</t></r></is></c>'
             '<c r="C1" t="s"><v>0</v></c><c r="D1" t="s"><v>1</v></c></row>'
             '<row r="2" spans="1:4"><c r="A2" t="inlineStr"><is><t>A&amp;B &lt;x&gt; &#8377; &#x20B9;</t></is></c><c r="B2" s="3"/>'
             '<c r="C2" t="b"><v>1</v></c><c r="D2" t="e"><v>#N/A</v></c></row>'
             '<row r="3"/>'
             '<row r="4"><c r="A4"><f>1+1</f><v>2</v></c><c r="D4" t="str"><f>A1</f><v>Reference Number</v></c><c r="F4"><v/></c></row>'
             '</sheetData></worksheet>')
    shared = ('<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">'
              '<si><t>Type of Transaction</t></si><si><r><t>Am</t></r><r><rPr><b/></rPr><t>ount</t></r><rPh sb="0" eb="1"><t>phonetic</t></rPh></si></sst>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   '<sheet name="Success" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", shared)
    for et, fast in _both(buf.getvalue()):
        assert fast == et
        assert et[1][0] == "A&B <x> ₹ ₹" and et[0][1] == "CSP Code"


def test_unsupported_markup_falls_back_to_elementtree():
    sheet = ('<x:worksheet xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><x:sheetData>'
             '<x:row r="1"><x:c r="A1"><x:v>5</x:v></x:c></x:row></x:sheetData></x:worksheet>')
    with pytest.raises(fp._FastParseUnsupported):
        fp._parse_sheet_xml_fast(sheet, [])


def test_full_reader_output_unchanged_for_transaction_upload(monkeypatch):
    content = _workbook_bytes(_tricky)
    fast_df, *fast_rest = fp.read_uploaded_file("tx.xlsx", content, None, "transactions")
    monkeypatch.setattr(fp, "_parse_sheet_xml", fp._parse_sheet_xml_et)
    monkeypatch.setattr(fp, "_shared_strings_fast", lambda z: (_ for _ in ()).throw(fp._FastParseUnsupported()))
    et_df, *et_rest = fp.read_uploaded_file("tx.xlsx", content, None, "transactions")
    pd.testing.assert_frame_equal(fast_df, et_df)
    assert fast_rest == et_rest and fast_df.attrs == et_df.attrs


def _supplement_like(wb):
    ws = wb.active; ws.title = "Women CSP Aug-26"
    ws.append(["Women CSP roster — August 2026"]); ws.append(["Region:", "Patna"]); ws.append([])
    ws.append(["Sl No", "CSP ID", "CSP Name", "Txn Count Aug-26", "Total Login Day Aug-26", "Status"])
    ws.append([1, "Other issue", "Sample Agent", 573, 22, "Active"])
    ws.append([2, "1A859006", "SAMPLE AGENT", 0, None, None])
    ws.append([3, 12345678, "Asha", 1e3, 20.5, dt.date(2026, 8, 31)])
    ws.append([None, None, None, None, None, None])
    ws.append(["Total", None, None, "=SUM(D5:D7)", None, None])
    wb.create_sheet("BC Payment Status").append(["CSP Code", "TOTAL COMM", "PENALTY AMOUNT"])
    wb["BC Payment Status"].append(["1A859006", 1234.5678, 0])


@pytest.mark.parametrize("header", [None, 0, 3])
def test_calamine_and_openpyxl_give_identical_frames(header):
    from app.services import excel_io
    if excel_io.ENGINE != "calamine":
        pytest.skip("python-calamine not installed")
    content = _workbook_bytes(_supplement_like)
    for sheet in ("Women CSP Aug-26", "BC Payment Status") if header in (None, 0) else ("Women CSP Aug-26",):
        fast = excel_io.read_excel(content, sheet_name=sheet, header=header, engine="openpyxl")
        ref = pd.read_excel(io.BytesIO(content), sheet_name=sheet, header=header, engine="openpyxl")
        pd.testing.assert_frame_equal(fast, ref)
    assert excel_io.excel_file(content).sheet_names == ["Women CSP Aug-26", "BC Payment Status"]


def test_excel_io_falls_back_to_openpyxl(monkeypatch):
    from app.services import excel_io
    content = _workbook_bytes(_supplement_like)
    real = pd.read_excel

    def failing(src, engine=None, **kw):
        if engine == "calamine":
            raise RuntimeError("simulated calamine failure")
        return real(src, engine=engine, **kw)

    monkeypatch.setattr(excel_io, "ENGINE", "calamine")
    monkeypatch.setattr(excel_io.pd, "read_excel", failing)
    df = excel_io.read_excel(content, sheet_name="BC Payment Status")
    assert df.loc[0, "TOTAL COMM"] == 1234.5678


# ------------------------------------------------------------ parallel scan (V62.6.214)
def _big_sheet_zip(rows=4000):
    """A hand-built workbook with shared strings, inline strings, numbers, booleans, entities, sparse cells,
    empty rows and rows that reach different columns."""
    shared = ["Reference Number", "CSP Code", "Type of Transaction", "Amount", "Status", "A & B <x>", "Notes", "SUCCESS", "line1\r\nline2"]
    sst = ('<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           + "".join(f"<si><t>{s.replace('&', '&amp;').replace('<', '&lt;')}</t></si>" for s in shared)
           + '<si><r><t>rich </t></r><r><t>text</t></r></si></sst>')
    parts = ['<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c><c r="E1" t="s"><v>4</v></c></row>']
    for i in range(2, rows + 2):
        cells = [f'<c r="A{i}" t="inlineStr"><is><t>REF-{i:08d}</t></is></c>', f'<c r="B{i}" s="2" t="s"><v>{5 + i % 3 * 0}</v></c>',
                 f'<c r="C{i}"><v>{1000 + i}.5</v></c>', f'<c r="D{i}" t="b"><v>{i % 2}</v></c>', f'<c r="E{i}" t="s"><v>{7 if i % 5 else 9}</v></c>']
        if i % 7 == 0:
            cells.append(f'<c r="G{i}" t="inlineStr"><is><t>wide &amp; sparse</t></is></c>')     # reaches a further column than most rows
        if i % 11 == 0:
            cells = cells[:1]                                                                      # short row
        if i % 13 == 0:
            parts.append(f'<row r="{i}"/>')                                                        # empty row
            continue
        parts.append(f'<row r="{i}">' + "".join(cells) + "</row>")
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<dimension ref="A1:G9999"/><sheetData>' + "".join(parts) + "</sheetData></worksheet>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Success" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", sst)
    return buf.getvalue()


def test_parallel_scan_gives_exactly_the_single_process_result(monkeypatch):
    from app import xlsx_scan
    monkeypatch.setenv("EKO_XLSX_WORKERS", "2")
    content = _big_sheet_zip()
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        shared = fp._shared_strings_fast(z)
        text = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert shared[-1] == "rich text"
    try:
        single = fp._parse_sheet_xml_fast(text, shared)
        parallel = xlsx_scan.parse_parallel(text, shared)
    finally:
        xlsx_scan.shutdown_pool()
    assert parallel == single and len(single) > 3000
    assert any(row[6] == "wide & sparse" for row in single) and any(row[1:] == [None] * (len(row) - 1) for row in single)


def test_read_uploaded_file_is_identical_with_and_without_worker_processes(monkeypatch):
    from app import xlsx_scan
    content = _big_sheet_zip(6000)
    monkeypatch.setenv("EKO_XLSX_WORKERS", "0")
    plain = fp.read_uploaded_file("tx.xlsx", content, None, "transactions")
    monkeypatch.setenv("EKO_XLSX_WORKERS", "2"); monkeypatch.setenv("EKO_XLSX_PARALLEL_MIN_BYTES", "1000")
    assert xlsx_scan.parallel_available(len(content))
    try:
        par = fp.read_uploaded_file("tx.xlsx", content, None, "transactions")
    finally:
        xlsx_scan.shutdown_pool()
    pd.testing.assert_frame_equal(plain[0], par[0])
    assert plain[1:] == par[1:] and plain[0].attrs == par[0].attrs


def test_a_broken_worker_pool_falls_back_to_the_single_process_scan(monkeypatch):
    from app import xlsx_scan
    content = _big_sheet_zip(500)
    monkeypatch.setenv("EKO_XLSX_WORKERS", "0")
    expected = fp.read_uploaded_file("tx.xlsx", content, None, "transactions")[0]
    monkeypatch.setenv("EKO_XLSX_WORKERS", "2"); monkeypatch.setenv("EKO_XLSX_PARALLEL_MIN_BYTES", "1000")
    monkeypatch.setattr(xlsx_scan, "parse_parallel", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pool died")))
    pd.testing.assert_frame_equal(fp.read_uploaded_file("tx.xlsx", content, None, "transactions")[0], expected)


def test_parallel_stays_off_for_small_files_and_without_an_importable_main(monkeypatch):
    from app import xlsx_scan
    monkeypatch.setenv("EKO_XLSX_WORKERS", "4")
    assert not xlsx_scan.parallel_available(1_000_000)                   # below the size threshold
    assert xlsx_scan.parallel_available(100 * 1024 * 1024)
    import sys
    monkeypatch.setattr(sys.modules["__main__"], "__spec__", None, raising=False)
    monkeypatch.setattr(sys.modules["__main__"], "__file__", "<stdin>", raising=False)
    assert not xlsx_scan.parallel_available(100 * 1024 * 1024)
