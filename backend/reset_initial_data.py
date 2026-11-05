"""Initialize a clean, month-agnostic upload state on every project startup.

The user explicitly requires every close/reopen to request fresh current-period
uploads. Therefore, active period data and generated results are cleared on each
start. Permanent approved SBI rule books and mapping catalogs are preserved.
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'app' / 'data'
VERSION = '62.6.216-ui-security-speed'
MARKER = ROOT.parent / '.eko_reconciliation_initialized_version'


def main():
    # ZIP archives do not preserve empty runtime directories. Create the data root
    # before cleanup/metadata writes so a clean extraction can start successfully.
    DATA.mkdir(parents=True, exist_ok=True)
    # Ensure expected runtime subdirectories exist even when absent from the ZIP.
    for folder in ('transactions', 'commissions', 'rate_master', 'csp_geography', 'rural_csp', 'supplemental', 'audit', 'processing', 'expected_commission_rule'):
        (DATA / folder).mkdir(parents=True, exist_ok=True)
    # Remove all active-period sources and generated results. The approved SBI
    # rules/mapping catalogs remain available as reference; uploaded period data
    # (including the rate master) must be selected for the intended reconciliation.
    clear_patterns = {
        'transactions': ['latest_transactions.csv', 'latest_transactions_raw.csv', 'processing_snapshot.json'],
        'commissions': ['latest_commission.csv', 'latest_commission_raw.csv'],
        # Preserve the permanent approved rule workbook; clear only its normalized
        # runtime copy so startup can rebuild it from the bundled permanent master.
        'rate_master': ['latest_rate_master.csv'],
        'csp_geography': ['latest_csp_geography.csv'],
        'rural_csp': ['latest_rural_csp_master.csv'],
        'supplemental': [
            'latest_social_security_counts.csv', 'latest_social_security_counts_exceptions.csv',
            'latest_social_security_csp_master.csv',
            'latest_passbook_printing_counts.csv', 'latest_passbook_printing_reconciliation.csv',
            'latest_dfs_incentive_counts.csv', 'latest_dfs_incentive_metadata.json',
            'latest_women_csp_roster.csv', 'latest_women_csp_roster_metadata.json',
            'latest_csp_identity_crosswalk.csv', 'latest_csp_identity_crosswalk_metadata.json',
            'latest_tab_incentive_counts.csv', 'latest_tab_incentive_metadata.json',
            'latest_matm_incentive_counts.csv', 'latest_matm_incentive_metadata.json',
            'latest_loan_lead_generation.csv', 'latest_loan_lead_generation_metadata.json'
        ],
        'audit': ['latest_condition_audit.csv', 'latest_condition_summary.json'],  # Preserve the durable audit/history source across clean starts.
        'processing': ['processing_snapshot.json'],
    }
    for folder, names in clear_patterns.items():
        directory = DATA / folder
        for name in names:
            path = directory / name
            if path.exists() and path.is_file():
                path.unlink()

    for name in ('reconciliation_cache.csv', 'reconciliation_cache_meta.json'):
        path = DATA / name
        if path.exists() and path.is_file():
            path.unlink()

    meta = {
        'transactions': None, 'commission': None, 'rate_master': None,
        'csp_geography': None, 'rural_csp': None,
        'social_security_counts': None, 'passbook_printing_counts': None,
        'dfs_incentive': None, 'women_csp_roster': None, 'tab_incentive': None, 'matm_incentive': None, 'loan_lead_generation': None,
        'expected_commission_rule': {
            'filename': 'SBI_Expected_Commission_Rule.xlsx',
            'sheet_name': 'Consolidated Commission Master',
            'rows': 71, 'period_start': None, 'period_end': None,
            'uploaded_at': None, 'sha256': None,
            'available_sheets': ['Consolidated Commission Master', 'Slabs & Incentive Matrices']
        },
        'active_batch_id': None, 'upload_attempt_errors': {}
    }
    # The commercial rule master is permanent and month-agnostic, unlike uploaded
    # transaction/commission data. Build its normalized deterministic rules on clean
    # start so the user does not need to re-upload the approved master every month.
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        from app.services.rate_master import build_rate_master_from_workbook, apply_confirmed_remittance_reference_rules
        rule_book = ROOT / 'app' / 'data' / 'expected_commission_rule' / 'latest.xlsx'
        if rule_book.exists():
            normalized, validation = build_rate_master_from_workbook(rule_book.read_bytes(), 'SBI_Expected_Commission_Rule.xlsx')
            if validation.get('valid') and not normalized.empty:
                normalized = apply_confirmed_remittance_reference_rules(normalized)
                from app.services.rate_master import apply_sbi_pdf_schedule_rules
                normalized = apply_sbi_pdf_schedule_rules(normalized)
                rm_dir = DATA / 'rate_master'
                rm_dir.mkdir(parents=True, exist_ok=True)
                normalized.to_csv(rm_dir / 'latest_rate_master.csv', index=False)
                batch_id = None
                meta['active_batch_id'] = None
                meta['rate_master'] = {
                    'filename': 'SBI_Expected_Commission_Rule.xlsx',
                    'sheet_name': validation.get('selected_sheet'),
                    'rows': int(len(normalized)), 'rules': int(len(normalized)), 'source_rules': int(validation.get('rules', len(normalized))),
                    'transaction_types': int(normalized['transaction_type'].nunique()) if 'transaction_type' in normalized else 0,
                    'period_start': None, 'period_end': None, 'uploaded_at': None,
                    'sha256': None, 'batch_id': batch_id,
                    'validation': {**validation, 'parser_version': VERSION}
                }
                meta['expected_commission_rule']['validation'] = {**validation, 'available_sheets': __import__('pandas').ExcelFile(rule_book, engine='openpyxl').sheet_names}
                meta['expected_commission_rule']['available_sheets'] = __import__('pandas').ExcelFile(rule_book, engine='openpyxl').sheet_names
                meta['expected_commission_rule']['rules'] = int(len(normalized))
                meta['expected_commission_rule']['source_rules'] = int(validation.get('rules', len(normalized)))
    except Exception as exc:
        print(f'Warning: permanent SBI rule master could not be normalized on startup: {exc}')
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / 'upload_metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    MARKER.write_text(VERSION, encoding='utf-8')
    print('Initialized clean month-agnostic state on startup. Upload fresh current-period sources to reconcile.')


if __name__ == '__main__':
    main()
