import pandas as pd
from .number_parser import parse_numeric_series, parse_date_series
from .transaction_processor import SUCCESS_STATUSES
from .fast_text import stripped, stripped_upper, on_unique
TRANSACTION_ALIASES={
"transaction_id":["transaction_id","transactionid","txn_id","txn","reference","reference_id","transaction_reference","reference_number","rrn","rrn_number"],
"csp_id":["csp_id","csp","csp_code","csp_code_new","cspcode","cspid","agent_id","bc_id"],
"transaction_type":["transaction_type","txn_type","transactiontype","type_of_transaction","service_type","service","txn_category"],
"amount":["amount","transaction_amount","txn_amount","trans_amount"],
"status":["status","transaction_status","txn_status","response_status"],
"transaction_date":["transaction_date","transaction_datetime","transaction_date_time","date","new_date"],
"channel":["channel","population","location_type","area_type","csp_category","csp_location"],
"kyc_type":["kyc_type","kyc","kyc_status","kyc_mode","kyc_type_mode","document_type","account_opening_mode"],"account_id":["account_id","account_number","customer_account_number","customer_account_id"]}
COMMISSION_ALIASES={
"csp_id":TRANSACTION_ALIASES["csp_id"],"transaction_type":TRANSACTION_ALIASES["transaction_type"],
"actual_commission":["actual_commission","commission","commission_amount","actual_comm","payout","revenue","commission_value"],
"report_base":["report_base","num_txns_avg_bal","num_txns","transaction_count","base"],"commission_date":["commission_date","transaction_date","date","month","period","report_date"]}

def standardize_schema(df,aliases):
    result=df; mapping={}
    for standard,candidates in aliases.items():
        for candidate in candidates:
            if candidate in result.columns:
                mapping[candidate]=standard; break
    return result.rename(columns=mapping),mapping

def _blank_count(s):
    return _blank_count_of_stripped(stripped(s))

def _blank_count_of_stripped(x):
    return int(x.isna().sum() + x.fillna('').eq('').sum())

def validate_transaction_data(df):
    df,m=standardize_schema(df,TRANSACTION_ALIASES)
    req=["transaction_id","csp_id","transaction_type","amount","transaction_date"]
    missing=[x for x in req if x not in df.columns]
    if missing:
        return df,{"valid":False,"missing_columns":missing,"mapped_columns":m,"rows":len(df),"errors":[f"Missing required columns: {', '.join(missing)}"]}
    amount=parse_numeric_series(df['amount'])
    invalid=int(amount.isna().sum())
    # Each text column is stripped once and reused below (blank counts, eligibility mask).
    ref=df['transaction_id'].astype('string').str.strip()
    csp_stripped=stripped(df['csp_id']); type_stripped=stripped(df['transaction_type'])
    status_stripped=stripped(df['status']) if 'status' in df.columns else None
    blank_txid=_blank_count_of_stripped(ref); blank_csp=_blank_count_of_stripped(csp_stripped); blank_type=_blank_count_of_stripped(type_stripped); blank_status=_blank_count_of_stripped(status_stripped) if status_stripped is not None else 0
    dup=int(ref[ref.notna() & ref.ne('')].duplicated(keep=False).sum())
    # The upload endpoint is explicitly the *Successful Transaction File* slot.
    # Some operational extracts contain a Status column; others are already
    # success-only and omit Status entirely.  In the latter case every uploaded
    # row is treated as successful, but the validation records that assumption
    # explicitly so it is auditable rather than silently inferred elsewhere.
    status_present='status' in df.columns
    if status_present:
        status_norm=on_unique(status_stripped, lambda x: x.str.upper())
        success_mask=status_norm.isin(SUCCESS_STATUSES)
    else:
        success_mask=pd.Series(True,index=df.index)
        df['status']='SUCCESS'
        status_present=False
    dup_success=int(ref[success_mask & ref.notna() & ref.ne('')].duplicated(keep=False).sum())
    negative_success=int((success_mask & amount.notna() & amount.lt(0)).sum())
    parsed_dates=parse_date_series(df['transaction_date'])
    missing_date=int(parsed_dates.isna().sum())
    date_ok=parsed_dates.notna()
    if status_stripped is None or not status_present:
        status_stripped=stripped(df['status'])         # the column was just filled with SUCCESS above
    processable=(amount.notna() & ref.notna() & ref.ne('') & csp_stripped.ne('') & type_stripped.ne('') & status_stripped.ne('') & date_ok)
    warnings=[]
    if invalid: warnings.append(f"{invalid} row(s) have invalid/non-numeric amount and will be excluded from eligible financial calculation; raw rows remain preserved for audit.")
    if blank_txid: warnings.append(f"{blank_txid} row(s) have blank transaction reference and will be excluded from eligible financial calculation.")
    if blank_csp: warnings.append(f"{blank_csp} row(s) have blank CSP and will be excluded from eligible financial calculation.")
    if blank_type: warnings.append(f"{blank_type} row(s) have blank transaction type and will be excluded from eligible financial calculation.")
    if status_present and blank_status: warnings.append(f"{blank_status} row(s) have blank status and will not be treated as successful.")
    if not status_present: warnings.append('No Status column was present; because this file was uploaded as the Successful Transaction File, every valid source row is explicitly treated as SUCCESS. This assumption is recorded for audit.')
    if dup: warnings.append(f"{dup} row(s) belong to duplicate transaction references. They are preserved and flagged; they are not silently removed.")
    if dup_success: warnings.append(f"{dup_success} successful row(s) belong to duplicate transaction references. The financial run will be blocked until the successful duplicate population is resolved.")
    if negative_success: warnings.append(f"{negative_success} successful row(s) have negative transaction amounts. Reversal/refund treatment must be explicitly approved before financial reconciliation.")
    if missing_date: warnings.append(f"{missing_date} row(s) have no usable transaction date and will be excluded from the eligible financial population until corrected.")
    invalid_success_rows=int((success_mask & ~processable).sum())
    valid=len(df)>0 and not missing
    return df,{"valid":valid,"missing_columns":missing,"mapped_columns":m,"rows":len(df),"processable_rows":int(processable.sum()),"excluded_rows":int((~processable).sum()),"duplicate_transaction_ids":dup,"duplicate_successful_transaction_ids":dup_success,"negative_success_amount_rows":negative_success,"missing_transaction_date":missing_date,
               "missing_csp":blank_csp,"missing_transaction_type":blank_type,"missing_transaction_id":blank_txid,"missing_status":blank_status,"status_column_present":status_present,"status_assumed_success":not status_present,
               "invalid_amounts":invalid,"invalid_success_rows":invalid_success_rows,"warning_duplicate_transaction_ids":dup>0,"errors":[],"warnings":warnings}

def validate_commission_data(df):
    df,m=standardize_schema(df,COMMISSION_ALIASES)
    req=["csp_id","transaction_type","actual_commission"]
    missing=[x for x in req if x not in df.columns]
    if missing:
        return df,{"valid":False,"missing_columns":missing,"mapped_columns":m,"rows":len(df),"errors":[f"Missing required columns: {', '.join(missing)}"]}
    commission=parse_numeric_series(df['actual_commission'])
    invalid=int(commission.isna().sum())
    invalid_base=int(parse_numeric_series(df['report_base']).isna().sum()) if 'report_base' in df else 0
    blank_csp=_blank_count(df['csp_id']); blank_type=_blank_count(df['transaction_type'])
    processable=commission.notna() & df['csp_id'].astype('string').str.strip().ne('') & df['transaction_type'].astype('string').str.strip().ne('')
    warnings=[]
    if invalid: warnings.append(f"{invalid} commission row(s) have invalid/non-numeric commission and will be excluded from monetary matching; raw rows remain preserved.")
    if blank_csp: warnings.append(f"{blank_csp} commission row(s) have blank CSP and will be excluded from monetary matching.")
    if blank_type: warnings.append(f"{blank_type} commission row(s) have blank transaction type and will be excluded from monetary matching.")
    if invalid_base: warnings.append(f"{invalid_base} report-base values are blank/non-numeric; they remain unavailable and are never treated as transaction counts.")
    date_source=next((src for src,std in m.items() if std=='commission_date'),None)
    date_granularity='month' if date_source in {'month','period'} else ('date' if date_source else None)
    return df,{"valid":len(df)>0,"missing_columns":missing,"mapped_columns":m,"rows":len(df),"processable_rows":int(processable.sum()),"excluded_rows":int((~processable).sum()),"invalid_commission_values":invalid,
               "invalid_report_base_values":invalid_base,"transaction_id_present":False,"commission_date_source":date_source,"commission_date_granularity":date_granularity,"errors":[],"warnings":warnings}

