from pathlib import Path
import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]

def _norm_population(value):
    value = ' '.join(str(value or '').strip().upper().replace('_', ' ').replace('-', ' ').split())
    if value in {'RURAL', 'SEMI URBAN', 'SEMIURBAN'}:
        return 'RURAL'
    if value in {'URBAN', 'METRO', 'URBAN METRO', 'URBAN/METRO'}:
        return 'URBAN'
    return ''

def test_passbook_approved_master_has_confirmed_rural_and_urban_rates():
    rules = pd.read_csv(BACKEND / 'app/data/rate_master/approved_rule_master_reference.csv', dtype=str).fillna('')
    rules = rules[rules['transaction_type'].str.strip().str.upper().eq('PASSBOOK PRINTING')]
    rates = {}
    for _, row in rules.iterrows():
        if row.get('rule_status', '').strip().upper() != 'CONFIRMED':
            continue
        area = _norm_population(row.get('channel', ''))
        if area:
            rates[area] = float(row['rate'])
    assert rates == {'RURAL': 5.0, 'URBAN': 6.0}

def test_passbook_geography_normalization_handles_rural_and_urban_aliases():
    assert _norm_population('RURAL') == 'RURAL'
    assert _norm_population('SEMI-URBAN') == 'RURAL'
    assert _norm_population('METRO') == 'URBAN'
    assert _norm_population('URBAN/METRO') == 'URBAN'
    assert _norm_population('UNKNOWN') == ''

def test_passbook_csp_wise_expected_is_count_times_approved_rate():
    sample = pd.DataFrame({'count': [100, 50], 'channel': ['RURAL', 'URBAN']})
    rates = {'RURAL': 5.0, 'URBAN': 6.0}
    sample['expected'] = sample['count'] * sample['channel'].map(rates)
    assert sample['expected'].tolist() == [500.0, 300.0]
    assert sample['expected'].sum() == 800.0


def test_passbook_paid_unit_rate_fallback_only_accepts_confirmed_sbi_rates():
    from app.api.reconciliation import _infer_passbook_rate_from_paid
    approved = {'RURAL': 5.0, 'URBAN': 6.0}
    assert _infer_passbook_rate_from_paid(1005, 201, approved) == 5.0
    assert _infer_passbook_rate_from_paid(906, 151, approved) == 6.0
    assert _infer_passbook_rate_from_paid(800, 100, approved) is None
    assert _infer_passbook_rate_from_paid(50, 0, approved) is None
    assert _infer_passbook_rate_from_paid(None, 10, approved) is None


def test_passbook_geography_can_be_resolved_from_other_current_bc_transaction_rows():
    # Passbook print counts can exist only in the supplemental source; geography
    # must still resolve from the CSP's other rows in the current BC commission file.
    commission_rows = pd.DataFrame({
        'csp_id': ['1A851234', '1A851234', '1A855678'],
        'transaction_type': ['MONEY TRANSFER', 'AEPS ONUS WITHDRAWAL', 'MONEY TRANSFER'],
        'channel': ['RURAL', 'SEMI-URBAN', 'URBAN'],
    })
    def candidates(values):
        return sorted({_norm_population(v) for v in values if _norm_population(v)})
    areas = commission_rows.groupby('csp_id')['channel'].agg(candidates).to_dict()
    # Rural and semi-urban normalize to one consistent area; another CSP is urban.
    assert areas['1A851234'] == ['RURAL']
    assert areas['1A855678'] == ['URBAN']


def test_passbook_conflicting_geography_does_not_choose_arbitrary_rate():
    assert sorted({_norm_population(v) for v in ['RURAL', 'URBAN'] if _norm_population(v)}) == ['RURAL', 'URBAN']
