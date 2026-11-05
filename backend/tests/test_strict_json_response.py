import math
import json
import numpy as np
import pandas as pd
from app.main import StrictJSONResponse


def test_strict_json_response_converts_non_finite_numbers_to_null():
    response = StrictJSONResponse({
        'nan': float('nan'),
        'positive_inf': float('inf'),
        'negative_inf': float('-inf'),
        'numpy_nan': np.float64('nan'),
        'pandas_na': pd.NA,
        'nested': [{'value': np.float64(12.5)}],
    })
    payload = json.loads(response.body.decode('utf-8'))
    assert payload['nan'] is None
    assert payload['positive_inf'] is None
    assert payload['negative_inf'] is None
    assert payload['numpy_nan'] is None
    assert payload['pandas_na'] is None
    assert payload['nested'][0]['value'] == 12.5


def test_strict_json_response_emits_valid_json_for_finite_values():
    response = StrictJSONResponse({'count': 3, 'rate': 0.614})
    payload = json.loads(response.body.decode('utf-8'))
    assert payload == {'count': 3, 'rate': 0.614}
