import re
import pandas as pd


def actual_loan_product(value):
    text = re.sub(r'[^A-Z0-9]+', ' ', str(value or '').upper()).strip()
    return {
        'P SEGMENT GOLD LOAN LEAD GENERATION': 'P-SEGMENT GOLD LOAN',
        'PERSONAL LOAN LEAD GENERATION': 'PERSONAL LOAN',
        'HOME LOAN LEAD GENERATION': 'HOME LOAN',
        'VEHICLE LOAN LEAD GENERATION': 'VEHICLE LOAN',
        'MUDRA LOAN LEAD GENERATION': 'MUDRA LOAN',
        'AGRI GOLD LOAN LEAD GENERATION': 'AGRI GOLD LOAN',
    }.get(text)


def infer_periods(value):
    text = str(value or '').upper()
    months = {
        'JAN': 1, 'JANUARY': 1, 'FEB': 2, 'FEBRUARY': 2, 'MAR': 3, 'MARCH': 3,
        'APR': 4, 'APRIL': 4, 'MAY': 5, 'JUN': 6, 'JUNE': 6, 'JUL': 7, 'JULY': 7,
        'AUG': 8, 'AUGUST': 8, 'SEP': 9, 'SEPT': 9, 'SEPTEMBER': 9,
        'OCT': 10, 'OCTOBER': 10, 'NOV': 11, 'NOVEMBER': 11, 'DEC': 12, 'DECEMBER': 12,
    }
    found = set()
    for name, month in months.items():
        for match in re.finditer(r'(?<![A-Z])' + name + r'(?![A-Z])', text):
            tail = text[match.end():match.end() + 10]
            ym = re.search(r'[-_ /]*(20\d{2}|\d{2})(?!\d)', tail)
            if ym:
                year = int(ym.group(1))
                year = year + 2000 if year < 100 else year
                if 2000 <= year <= 2100:
                    found.add(f'{year:04d}-{month:02d}')
    return sorted(found)


def build_reconciliation(leads, commission, commission_meta=None):
    lead_df = leads.copy()
    bc = commission.copy() if commission is not None else pd.DataFrame()
    commission_meta = commission_meta or {}
    lead_periods = sorted(lead_df['period'].dropna().astype(str).unique().tolist()) if 'period' in lead_df else []
    bc_periods = []
    for key in ('period_start', 'period_end'):
        if commission_meta.get(key):
            bc_periods.extend(infer_periods(commission_meta[key]))
    bc_periods.extend(infer_periods(commission_meta.get('filename', '')))
    bc_periods = sorted(set(bc_periods))
    period_aligned = bool(lead_periods and bc_periods and set(lead_periods).issubset(set(bc_periods)))
    actual_available = bool(not bc.empty and {'csp_id', 'transaction_type', 'actual_commission'}.issubset(bc.columns))
    actual_rows = []

    lead_df['csp_id'] = lead_df['csp_id'].astype(str).str.strip().str.upper()
    lead_df['loan_product'] = lead_df['loan_product'].where(lead_df['loan_product'].notna(), None)
    if 'loan_type_raw' not in lead_df:
        lead_df['loan_type_raw'] = lead_df['loan_product'].fillna('UNMAPPED').astype(str)
    lead_df['eligible_sanctioned'] = lead_df['status'].astype(str).str.contains(r'sanction', case=False, na=False)
    eligible_all = lead_df[lead_df['eligible_sanctioned']].copy()
    eligible = eligible_all[eligible_all['loan_product'].notna()].copy()
    eligible_unmapped = eligible_all[eligible_all['loan_product'].isna()].copy()

    if actual_available and period_aligned:
        b = bc.copy()
        b['csp_id'] = b['csp_id'].astype(str).str.strip().str.upper()
        b['loan_product'] = b['transaction_type'].map(actual_loan_product)
        b['actual_commission'] = pd.to_numeric(b['actual_commission'], errors='coerce')
        b['reported_units'] = pd.to_numeric(b['report_base'], errors='coerce') if 'report_base' in b else pd.NA
        b = b[b['loan_product'].notna() & b['actual_commission'].notna() & b['csp_id'].ne('')].copy()
        if not b.empty:
            grouped = b.groupby(['csp_id', 'loan_product'], dropna=False).agg(
                actual_commission=('actual_commission', 'sum'),
                actual_report_rows=('actual_commission', 'size'),
                actual_units=('reported_units', lambda values: pd.to_numeric(values, errors='coerce').sum(min_count=1)),
            ).reset_index()
            actual_rows = grouped.to_dict('records')

    lead_groups = []
    if not eligible.empty:
        # A final commission match requires the complete expected amount, including
        # the explicitly supplied GST rate because the SBI source rule says '+ GST'.
        # Never treat a base-only amount as fully matched when GST treatment is unknown.
        eligible = eligible.copy()
        if 'gst_amount' in eligible:
            eligible['expected_total_commission'] = pd.to_numeric(eligible['expected_base_commission'], errors='coerce') + pd.to_numeric(eligible['gst_amount'], errors='coerce')
            eligible.loc[pd.to_numeric(eligible['expected_base_commission'], errors='coerce').isna() | pd.to_numeric(eligible['gst_amount'], errors='coerce').isna(), 'expected_total_commission'] = float('nan')
        else:
            eligible['expected_total_commission'] = float('nan')
        grouped_leads = eligible.groupby(['csp_id', 'loan_product'], dropna=False).agg(
            eligible_leads=('lead_id', 'nunique'),
            lead_ids=('lead_id', lambda values: '; '.join(map(str, values))),
            source_loan_types=('loan_type_raw', lambda values: '; '.join(sorted(set(map(str, values)))) if 'loan_type_raw' in eligible.columns else ''),
            expected_base_commission=('expected_base_commission', lambda values: pd.to_numeric(values, errors='coerce').sum(min_count=1)),
            expected_total_commission=('expected_total_commission', lambda values: pd.to_numeric(values, errors='coerce').sum(min_count=1) if pd.to_numeric(values, errors='coerce').notna().all() else float('nan')),
        ).reset_index()
        lead_groups = grouped_leads.to_dict('records')

    lead_lookup = {(str(r['csp_id']), str(r['loan_product'])): r for r in lead_groups}
    actual_lookup = {(str(r['csp_id']), str(r['loan_product'])): r for r in actual_rows}
    keys = sorted(set(lead_lookup) | set(actual_lookup))
    match_rows = []
    for csp, product in keys:
        l = lead_lookup.get((csp, product), {})
        a = actual_lookup.get((csp, product), {})
        lead_count = int(l.get('eligible_leads') or 0)
        actual = float(a['actual_commission']) if a and pd.notna(a.get('actual_commission')) else None
        units_val = a.get('actual_units') if a else None
        actual_units = float(units_val) if units_val is not None and pd.notna(units_val) else None
        expected = float(l['expected_base_commission']) if l and pd.notna(l.get('expected_base_commission')) else None
        expected_total = float(l['expected_total_commission']) if l and pd.notna(l.get('expected_total_commission')) else None
        count_matches = actual is not None and actual_units is not None and round(actual_units) == lead_count and lead_count > 0
        if not period_aligned:
            status = 'PERIOD_UNVERIFIED'
        elif lead_count == 0 and actual is not None:
            status = 'ACTUAL_WITHOUT_ELIGIBLE_LEAD'
        elif actual is None and lead_count > 0:
            status = 'ELIGIBLE_LEAD_WITHOUT_ACTUAL_PAYOUT'
        elif actual is not None and lead_count > 0 and actual_units is None:
            status = 'COUNT_UNVERIFIED'
        elif count_matches and expected_total is None:
            status = 'COUNT_MATCH_AMOUNT_UNVERIFIED' if expected is None else 'COUNT_MATCH_GST_TREATMENT_UNVERIFIED'
        elif count_matches and expected_total is not None and abs(actual - expected_total) <= 0.01:
            status = 'MATCHED'
        elif count_matches and expected_total is not None:
            status = 'AMOUNT_MISMATCH'
        elif actual is not None and lead_count > 0:
            status = 'LEAD_PAYOUT_COUNT_MISMATCH'
        else:
            status = 'NO_ELIGIBLE_SANCTIONED_LEAD'
        match_rows.append({
            'period': lead_periods[0] if len(lead_periods) == 1 else ','.join(lead_periods),
            'csp_id': csp, 'loan_product': product, 'source_loan_type': l.get('source_loan_types', ''), 'eligible_sanctioned_leads': lead_count,
            'lead_ids': l.get('lead_ids', ''), 'actual_reported_units': actual_units,
            'actual_commission': round(actual, 2) if actual is not None else None,
            'expected_base_commission': round(expected, 2) if expected is not None else None,
            'expected_total_commission_including_gst': round(expected_total, 2) if expected_total is not None else None,
            'variance': round(actual - expected_total, 2) if actual is not None and expected_total is not None else None,
            'status': status,
        })

    # Sanctioned leads whose source product cannot be safely mapped to an SBI product
    # still appear as explicit unresolved controls. They must not silently disappear
    # from the control population or be assigned a guessed rate.
    if not eligible_unmapped.empty:
        for (csp, raw_product), group in eligible_unmapped.groupby(['csp_id', 'loan_type_raw'], dropna=False):
            match_rows.append({
                'period': lead_periods[0] if len(lead_periods) == 1 else ','.join(lead_periods),
                'csp_id': str(csp), 'loan_product': None, 'source_loan_type': str(raw_product),
                'eligible_sanctioned_leads': int(group['lead_id'].nunique()),
                'lead_ids': '; '.join(group['lead_id'].astype(str)),
                'actual_reported_units': None, 'actual_commission': None,
                'expected_base_commission': None, 'expected_total_commission_including_gst': None,
                'variance': None, 'status': 'PRODUCT_MAPPING_REQUIRED',
            })

    sanction_limits = pd.to_numeric(lead_df['sanction_limit'], errors='coerce') if 'sanction_limit' in lead_df else pd.Series(dtype=float)
    expected_values = pd.to_numeric(lead_df['expected_base_commission'], errors='coerce') if 'expected_base_commission' in lead_df else pd.Series(dtype=float)
    actual_total = round(sum(float(r['actual_commission']) for r in actual_rows), 2) if actual_rows and period_aligned else None
    status_counts = {}
    for row in match_rows:
        status_counts[row['status']] = status_counts.get(row['status'], 0) + 1
    summary = {
        'rows': int(len(lead_df)),
        'periods': lead_periods,
        'unique_csp_count': int(lead_df['csp_id'].nunique()),
        'unique_lead_count': int(lead_df['lead_id'].nunique()),
        'product_counts': {('UNMAPPED' if pd.isna(k) else str(k)): int(v) for k, v in lead_df.groupby('loan_product', dropna=False).size().items()},
        'sanction_limit_rows': int(sanction_limits.notna().sum()),
        'base_calculated_rows': int(expected_values.notna().sum()),
        'unresolved_sanction_limit_rows': int(sanction_limits.isna().sum()),
        'sanction_evidence_missing_rows': int((~lead_df['status'].astype(str).str.contains(r'sanction', case=False, na=False)).sum()),
        'unmapped_product_rows': int(lead_df['loan_product'].isna().sum()),
        'unmapped_eligible_control_groups': int(eligible_unmapped.groupby(['csp_id', 'loan_type_raw'], dropna=False).ngroups) if not eligible_unmapped.empty else 0,
        'expected_base_commission_total': round(float(expected_values.sum()), 2) if expected_values.notna().any() else None,
        'expected_total_commission_including_gst_total': round(float(pd.to_numeric(lead_df.get('expected_base_commission'), errors='coerce').add(pd.to_numeric(lead_df.get('gst_amount'), errors='coerce')).sum()), 2) if ('expected_base_commission' in lead_df and 'gst_amount' in lead_df and pd.to_numeric(lead_df['expected_base_commission'], errors='coerce').notna().any() and pd.to_numeric(lead_df['gst_amount'], errors='coerce').notna().all()) else None,
        'actual_commission_total': actual_total,
        'actual_commission_rows': sum(int(r['actual_report_rows']) for r in actual_rows) if period_aligned else 0,
        'actual_commission_csp_product_groups': len(actual_rows) if period_aligned else 0,
        'count_matched_groups': sum(1 for r in match_rows if r['status'] in ('MATCHED', 'COUNT_MATCH_AMOUNT_UNVERIFIED', 'COUNT_MATCH_GST_TREATMENT_UNVERIFIED')),
        'period_aligned': period_aligned,
        'commission_periods_detected': bc_periods,
        'actual_payout_status': 'VERIFIED_PERIOD' if period_aligned and actual_available else ('PERIOD_MISMATCH_OR_UNVERIFIED' if actual_available else 'BC_REPORT_REQUIRED'),
        'match_status_counts': status_counts,
        'gst_rate_source': 'GST is calculated only when an explicit GST rate is supplied; no rate is inferred.',
    }
    unresolved = summary['unresolved_sanction_limit_rows'] + summary['unmapped_product_rows']
    ready = period_aligned and unresolved == 0 and bool(match_rows) and all(r['status'] == 'MATCHED' for r in match_rows)
    return {
        'available': True, 'status': 'READY' if ready else 'PROVISIONAL', 'periods': lead_periods,
        'summary': summary,
        'rows': lead_df.where(pd.notna(lead_df), None).to_dict('records'),
        'match_rows': match_rows,
        'message': 'Actual payout lines are compared by CSP + approved loan product for the same period. MATCHED requires a documented sanction limit, explicit GST treatment and expected total within ₹0.01 of actual payout; count-only matches remain provisional. Sanctioned leads with unresolved product mapping are shown as exception controls, not silently dropped.',
    }
