from io import BytesIO
import pandas as pd


def _extract_geography_from_current_bc_workbook(content: bytes):
    """Mirror the BC upload contract: derive geography from this workbook only."""
    xl = pd.ExcelFile(BytesIO(content), engine="openpyxl")
    ps_name = next((x for x in xl.sheet_names if str(x).strip().upper() == "PAYMENT STATUS"), None)
    if not ps_name:
        return {}
    ps = pd.read_excel(BytesIO(content), sheet_name=ps_name, engine="openpyxl")
    ps.columns = (ps.columns.astype(str).str.strip().str.lower()
                  .str.replace(r"[^a-z0-9]+", "_", regex=True).str.strip("_"))
    id_col = next((c for c in ("csp_id", "csp_code", "csp_code_new", "terminal_id") if c in ps.columns), None)
    if not id_col or "population" not in ps.columns:
        return {}
    geo = ps[[id_col, "population"]].copy()
    geo.columns = ["csp_id", "population"]
    geo["csp_id"] = geo["csp_id"].astype("string").str.strip().str.upper()
    geo["population_raw"] = geo["population"].astype("string").str.strip().str.upper()
    geo = geo[geo["csp_id"].ne("") & geo["population_raw"].ne("")].copy()
    geo["channel"] = geo["population_raw"].replace({
        "SEMI URBAN": "RURAL", "SEMI-URBAN": "RURAL", "SEMIURBAN": "RURAL",
        "URBAN/METRO": "URBAN", "METRO": "URBAN",
    })
    geo = geo[geo["channel"].isin(["RURAL", "URBAN"])]
    conflicts = geo.groupby("csp_id")["channel"].nunique()
    bad = set(conflicts[conflicts > 1].index)
    geo = geo[~geo["csp_id"].isin(bad)].drop_duplicates("csp_id")
    return dict(zip(geo["csp_id"], geo["channel"]))


def _workbook(rows):
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Payment Status", index=False)
        pd.DataFrame({"CSP_CODE": ["1A850001"], "TRANSACTION_TYPE": ["TEST"], "ACTUAL_COMMISSION": [1]}).to_excel(
            writer, sheet_name="CSP Wise Transaction Type Wise", index=False
        )
    return stream.getvalue()


def test_geography_comes_from_each_uploaded_workbook_not_fixed_month_data():
    august_like = _extract_geography_from_current_bc_workbook(_workbook([
        {"CSP_CODE": "1A850001", "POPULATION": "RURAL"},
        {"CSP_CODE": "1A850002", "POPULATION": "URBAN"},
    ]))
    september_like = _extract_geography_from_current_bc_workbook(_workbook([
        {"CSP_CODE": "1A850001", "POPULATION": "METRO"},
        {"CSP_CODE": "1A850002", "POPULATION": "SEMI URBAN"},
    ]))
    assert august_like == {"1A850001": "RURAL", "1A850002": "URBAN"}
    assert september_like == {"1A850001": "URBAN", "1A850002": "RURAL"}
    assert august_like != september_like


def test_conflicting_population_for_same_csp_is_not_arbitrarily_assigned():
    result = _extract_geography_from_current_bc_workbook(_workbook([
        {"CSP_CODE": "1A850001", "POPULATION": "RURAL"},
        {"CSP_CODE": "1A850001", "POPULATION": "URBAN"},
    ]))
    assert "1A850001" not in result
