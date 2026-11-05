# Revenue Reconciliation Backend

FastAPI backend for month-agnostic Eko/SBI revenue reconciliation.

## Run
```cmd
cd backend
%LOCALAPPDATA%\EkoSBI\venv_v62_6_115\Scripts\activate
uvicorn app.main:app --reload
```

API: http://127.0.0.1:8000
Swagger: http://127.0.0.1:8000/docs

## Upload order
Upload all three current-period inputs:
1. transaction file
2. BC/commission file
3. approved rate/slab master

Uploading a new transaction or commission file clears the old counterpart so files from different months cannot be mixed.


## V62.6.109 audit hardening

The reconciliation cache signature now fingerprints active supplemental sources, identity crosswalks, permanent mapping catalogs, rural mappings, source metadata, and period/batch identity. This prevents reuse of stale computed results after source/configuration changes even if file size or modification time is preserved.
