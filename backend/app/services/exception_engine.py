import pandas as pd

SEV={
 'Shortfall':'High','Excess':'Medium','Missing Commission Pair':'High',
 'Rate Master Missing':'High','Ambiguous Rate Rule':'High',
 'Count Mismatch':'Medium','SOURCE_COUNT_DIFFERENCE':'Medium','UNMAPPED':'Medium',
 'BC_ONLY_ACTIVITY':'Low','Unmapped Transaction Type':'Medium','Report Base Unavailable':'High'
}

def build_exceptions(r):
    x=r[r.exception_flag].copy()
    if x.empty:
        return pd.DataFrame(columns=['exception_id','csp_id','transaction_type','successful_transactions','report_base','count_variance','expected_commission','actual_commission','financial_gap','variance','reconciliation_status','financial_gap_status','investigation_status','mismatch_reason','mismatch_priority','severity','status'])
    x.insert(0,'exception_id',[f'EX-{i:05d}' for i in range(1,len(x)+1)])
    x['severity']=x.reconciliation_status.map(SEV).fillna('Medium')
    x['status']='Open'
    for c in ['investigation_status','mismatch_reason','mismatch_priority']:
        if c not in x.columns: x[c]=pd.NA

    # Root-cause/action layer: descriptive only; it never changes the financial calculation.
    root_map={
        'SOURCE_COUNT_DIFFERENCE': ('Source population/count difference', 'Investigate CSP + transaction-type count difference; check period/cut-off, reversals, source inclusion rules and BC reporting population.'),
        'BC_ONLY_ACTIVITY': ('BC-only activity', 'Verify whether the BC category is an incentive, average-balance, penalty or other non-transactional component, or whether a source population is missing.'),
        'UNMAPPED': ('Unmapped transaction type', 'Add or approve the operational-to-BC transaction-type mapping before settlement.'),
        'RATE_MASTER_MISSING': ('Missing commercial rule', 'Review the approved SBI rate/slab master and add/approve the missing transaction rule before settlement.'),
        'AMBIGUOUS_RATE_RULE': ('Ambiguous commercial rule', 'Resolve overlapping or ambiguous approved rate/slab rules.'),
        'MAPPING_PENDING': ('Mapping pending approval', 'Confirm the SBI product/rule mapping before treating calculated commission as settlement-approved.'),
        'Shortfall': ('Commission shortfall', 'Investigate why actual BC commission is below the approved expected commission for the comparable group.'),
        'Excess': ('Commission excess', 'Investigate why actual BC commission exceeds the approved expected commission for the comparable group.'),
        'Count Mismatch': ('Source population/count difference', 'Investigate CSP + transaction-type count difference between successful transactions and BC report.'),
        'Missing Commission Pair': ('Missing BC commission pair', 'Check why successful CSP + transaction-type activity has no corresponding BC commission row.'),
        'Rate Master Missing': ('Missing commercial rule', 'Review the approved SBI rate/slab master and add/approve the missing transaction rule before settlement.'),
        'Ambiguous Rate Rule': ('Ambiguous commercial rule', 'Resolve overlapping or ambiguous approved rate/slab rules.'),
        'Unmapped Transaction Type': ('Unmapped transaction type', 'Add or approve the operational-to-BC transaction-type mapping.'),
        'Mapping Pending - Provisional': ('Mapping pending approval', 'Confirm the SBI product/rule mapping before settlement.'),
    }
    pairs=x['reconciliation_status'].map(root_map)
    x['root_cause']=pairs.map(lambda v: v[0] if isinstance(v, tuple) else 'Reconciliation exception')
    x['recommended_action']=pairs.map(lambda v: v[1] if isinstance(v, tuple) else 'Review the CSP + transaction-type exception and source records.')
    return x[['exception_id','csp_id','transaction_type','successful_transactions','report_base','count_variance','expected_commission','actual_commission','financial_gap','variance','reconciliation_status','financial_gap_status','investigation_status','mismatch_reason','mismatch_priority','root_cause','recommended_action','severity','status']]
