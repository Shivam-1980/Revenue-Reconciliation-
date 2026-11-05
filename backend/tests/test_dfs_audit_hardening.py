import asyncio
from io import BytesIO
import pandas as pd
import pytest
from starlette.datastructures import UploadFile as StarletteUploadFile
from app.api import upload as upload_api
from app.services import rural_commission


def test_dfs_upload_accepts_assigned_slab_header_and_keeps_blank_name_with_valid_id(tmp_path, monkeypatch):
    supplemental = tmp_path / "supplemental"
    supplemental.mkdir()
    monkeypatch.setattr(upload_api, "SUPPLEMENTAL", supplemental)
    monkeypatch.setattr(upload_api, "DFS_COUNTS", supplemental / "latest_dfs_incentive_counts.csv")
    monkeypatch.setattr(upload_api, "DFS_META", supplemental / "latest_dfs_incentive_metadata.json")
    payload = (
        "CSP Code,CSP Name,Assigned Slab,Month Year\n"
        "1A851234,,Slab-1,August 2026\n"
        "1A851235,Test CSP,Super Slab,August 2026\n"
    ).encode()
    file = StarletteUploadFile(filename="dfs_Aug_2026.csv", file=BytesIO(payload))
    result = asyncio.run(upload_api.dfs_incentive(file=file))
    assert result["saved"] is True
    assert result["validation"]["rows"] == 2
    assert result["validation"]["expected_total"] == 6200
    stored = pd.read_csv(supplemental / "latest_dfs_incentive_counts.csv", dtype=str).fillna("")
    assert len(stored) == 2
    assert stored.loc[0, "csp_id"] == "1A851234"
    assert stored.loc[0, "csp_name"] == ""


def test_dfs_reconciliation_fails_closed_when_bc_period_unknown(tmp_path, monkeypatch):
    supplemental = tmp_path / "supplemental"
    commissions = tmp_path / "commissions"
    supplemental.mkdir(); commissions.mkdir()
    src = pd.DataFrame([
        {"csp_id":"1A851234","csp_name":"Test CSP","slab":"SLAB-1","expected_incentive":1200,
         "transaction_type":"DFS PRIORITIES INCENTIVE","period":"2026-08","source_file":"dfs_Aug_2026.csv"}
    ])
    src.to_csv(supplemental / "latest_dfs_incentive_counts.csv", index=False)
    pd.DataFrame([{"csp_id":"1A851234","csp_name":"Test CSP","transaction_type":"DFS PRIORITIES INCENTIVE","actual_commission":1200}]).to_csv(
        commissions / "latest_commission.csv", index=False)
    monkeypatch.setattr(upload_api, "DFS_COUNTS", supplemental / "latest_dfs_incentive_counts.csv")
    monkeypatch.setattr(upload_api, "CM", commissions)
    monkeypatch.setattr(upload_api, "load_metadata", lambda: {"commission": {"filename":"commission_report.xlsx"}})
    result = upload_api.dfs_incentive_reconciliation()
    assert result["available"] is False
    assert result["status"] == "BC_PERIOD_UNKNOWN"



def test_rural_csp_csv_monthly_source_is_supported_and_period_is_detected(tmp_path, monkeypatch):
    rural_dir = tmp_path / "rural_csp"
    rural_dir.mkdir()
    monkeypatch.setattr(upload_api, "RURAL_MASTER_PATH", rural_dir / "latest_rural_csp_master.csv")
    monkeypatch.setattr(rural_commission, "RURAL_MASTER_PATH", rural_dir / "latest_rural_csp_master.csv")
    monkeypatch.setattr(upload_api, "load_metadata", lambda: {})
    monkeypatch.setattr(upload_api, "clear_source", lambda key: None)
    monkeypatch.setattr(upload_api, "save_source", lambda *args, **kwargs: None)
    monkeypatch.setattr(upload_api, "clear_cache", lambda: None)
    payload = (
        "CSP ID,CSP Name,CSP Category,Total Login Day (Aug'26)\n"
        "1A851234,Test CSP,Silver CSP,29\n"
    ).encode()
    file = StarletteUploadFile(filename="Rural_CSP_Aug_2026.csv", file=BytesIO(payload))
    result = asyncio.run(upload_api.rural_csp(file=file))
    assert result["saved"] is True
    assert result["validation"]["period"] == "2026-08"
    stored = pd.read_csv(rural_dir / "latest_rural_csp_master.csv")
    assert len(stored) == 1 and stored.iloc[0]["login_days"] == 29


def test_dfs_permanent_matrix_uses_updated_slab4_and_all_targets():
    from app.api import upload as upload_api
    assert upload_api.DFS_RATES == {
        'SLAB-1': 1200.0,
        'SLAB-2': 1500.0,
        'SLAB-3': 1800.0,
        'SLAB-4': 2200.0,
        'SUPER SLAB': 5000.0,
    }
    matrix = upload_api.dfs_incentive_rules()['rule_matrix']
    assert [x['targets'] for x in matrix['schemes']] == [
        {'SLAB-1': 8, 'SLAB-2': 10, 'SLAB-3': 12, 'SLAB-4': 14, 'SUPER SLAB': 30},
        {'SLAB-1': 12, 'SLAB-2': 14, 'SLAB-3': 16, 'SLAB-4': 18, 'SUPER SLAB': 50},
        {'SLAB-1': 20, 'SLAB-2': 25, 'SLAB-3': 30, 'SLAB-4': 35, 'SUPER SLAB': 100},
        {'SLAB-1': 3, 'SLAB-2': 4, 'SLAB-3': 5, 'SLAB-4': 6, 'SUPER SLAB': 15},
    ]
    assert matrix['average_balance_multiplier_percent'] == {
        'SLAB-1': 0.85, 'SLAB-2': 0.90, 'SLAB-3': 0.95, 'SLAB-4': 1.00, 'SUPER SLAB': 1.00,
    }


def test_dfs_slab4_expected_amount_is_2200(tmp_path, monkeypatch):
    supplemental = tmp_path / 'supplemental'
    supplemental.mkdir()
    monkeypatch.setattr(upload_api, 'SUPPLEMENTAL', supplemental)
    monkeypatch.setattr(upload_api, 'DFS_COUNTS', supplemental / 'latest_dfs_incentive_counts.csv')
    monkeypatch.setattr(upload_api, 'DFS_META', supplemental / 'latest_dfs_incentive_metadata.json')
    payload = b'CSP Code,CSP Name,Assigned Slab,Month Year\n1A851234,Test CSP,Slab-4,October 2026\n'
    file = StarletteUploadFile(filename='dfs_Oct_2026.csv', file=BytesIO(payload))
    result = asyncio.run(upload_api.dfs_incentive(file=file))
    assert result['validation']['expected_total'] == 2200
    assert result['validation']['slab_rates']['SLAB-4'] == 2200


def test_dfs_name_resolution_uses_full_bc_population_and_rejects_ambiguous_names(tmp_path, monkeypatch):
    supplemental = tmp_path / "supplemental"
    commissions = tmp_path / "commissions"
    supplemental.mkdir(); commissions.mkdir()
    src = pd.DataFrame([
        {"csp_id":"", "csp_name":"Same Name", "slab":"SLAB-4", "expected_incentive":2200,
         "transaction_type":"DFS PRIORITIES INCENTIVE", "period":"2026-08", "source_file":"overall_CSP_DFS_Aug_2026.xlsx"},
        {"csp_id":"", "csp_name":"Unique Not Paid", "slab":"SLAB-1", "expected_incentive":1200,
         "transaction_type":"DFS PRIORITIES INCENTIVE", "period":"2026-08", "source_file":"overall_CSP_DFS_Aug_2026.xlsx"},
    ])
    src.to_csv(supplemental / "latest_dfs_incentive_counts.csv", index=False)
    bc = pd.DataFrame([
        {"csp_id":"1A851234","csp_name":"Same Name","transaction_type":"DFS PRIORITIES INCENTIVE","actual_commission":2200},
        {"csp_id":"1A851999","csp_name":"Same Name","transaction_type":"MONEY TRANSFER","actual_commission":10},
        {"csp_id":"1A851235","csp_name":"Unique Not Paid","transaction_type":"MONEY TRANSFER","actual_commission":10},
    ])
    bc.to_csv(commissions / "latest_commission.csv", index=False)
    monkeypatch.setattr(upload_api, "DFS_COUNTS", supplemental / "latest_dfs_incentive_counts.csv")
    monkeypatch.setattr(upload_api, "CM", commissions)
    monkeypatch.setattr(upload_api, "load_metadata", lambda: {
        "commission": {"filename":"BC_Report_Aug_2026.xlsx", "period_start":"2026-08-01", "period_end":"2026-08-31"}
    })
    result = upload_api.dfs_incentive_reconciliation()
    assert result["available"] is True
    statuses = {}
    for row in result["rows"]:
        statuses.setdefault(row["status"], []).append(row)
    # Same Name belongs to two CSP IDs somewhere in the full report, so the paid ID
    # must not be guessed from the DFS-only subset.
    assert len(statuses["UNRESOLVED_CSP_ID"]) == 1
    assert any(r["csp_id"] == "1A851234" for r in statuses["BC_ONLY_CSP"])
    # A unique name present in the full BC report but without a DFS payment is a
    # genuine missing-payment control, not an identity-unresolved row.
    assert len(statuses["MISSING_IN_BC"]) == 1
    assert statuses["MISSING_IN_BC"][0]["expected_incentive"] == 1200
    assert result["summary"]["unresolved_source_rows"] == 1
    assert "globally unique" in result["matching_policy"]


def test_legacy_overall_csp_dfs_xlsx_accepts_name_based_rows_without_official_id_column(tmp_path, monkeypatch):
    from io import BytesIO
    import openpyxl
    supplemental = tmp_path / "supplemental"
    supplemental.mkdir()
    monkeypatch.setattr(upload_api, "SUPPLEMENTAL", supplemental)
    monkeypatch.setattr(upload_api, "DFS_COUNTS", supplemental / "latest_dfs_incentive_counts.csv")
    monkeypatch.setattr(upload_api, "DFS_META", supplemental / "latest_dfs_incentive_metadata.json")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([None, None, None, None, None, None, None, None, None, "MTD Achievement August'26"])
    ws.append([None, "Total Login Day (Aug'26)", "CSP Name", "Gender", "CSP Mail ID", "CSP Mobile number", None, "CSP Category", "Relationship Manager", None])
    ws.append([None, "1A859007", "Abhimanyu Kumar Singh", "Male", "x@example.com", 9999999999, None, "Silver CSP", "Vandana", "Slab-1"])
    ws.append([None, 29, "Abhishek Kumar", "Male", "y@example.com", 9999999998, None, "Gold CSP", "Vandana", "Slab-4"])
    bio = BytesIO(); wb.save(bio); bio.seek(0)
    file = StarletteUploadFile(filename="overall CSP DFS.xlsx", file=bio)
    result = asyncio.run(upload_api.dfs_incentive(file=file))
    assert result["saved"] is True
    assert result["validation"]["periods"] == ["2026-08"]
    stored = pd.read_csv(supplemental / "latest_dfs_incentive_counts.csv", dtype=str).fillna("")
    assert len(stored) == 2
    assert stored.loc[0, "csp_id"] == "1A859007"
    assert stored.loc[1, "csp_id"] == ""
    assert stored.loc[1, "csp_name"] == "Abhishek Kumar"
