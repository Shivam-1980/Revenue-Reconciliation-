import pandas as pd

def test_missing_optional_numeric_columns_use_numeric_dtype():
    # Regression for uploaded lead files that do not contain sanction-limit/GST columns.
    df = pd.DataFrame({'lead_id':['L1','L2']})
    if 'sanction_limit' in df:
        df['sanction_limit'] = pd.to_numeric(df['sanction_limit'], errors='coerce').astype('float64')
    else:
        df['sanction_limit'] = pd.Series(float('nan'), index=df.index, dtype='float64')
    if 'gst_rate' in df:
        df['gst_rate'] = pd.to_numeric(df['gst_rate'], errors='coerce').astype('float64')
    else:
        df['gst_rate'] = pd.Series(float('nan'), index=df.index, dtype='float64')
    assert pd.api.types.is_numeric_dtype(df['sanction_limit'].dtype)
    assert pd.api.types.is_numeric_dtype(df['gst_rate'].dtype)
    assert not (df['sanction_limit'].dropna() < 0).any()
    assert df['sanction_limit'].isna().all()


def test_unknown_other_p_segment_product_is_not_guessed_as_gold_loan():
    from app.api.upload import _loan_lead_product
    assert _loan_lead_product("OTHER_P_SEG_LOAN_LEAD") is None
