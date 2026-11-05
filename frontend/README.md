# Revenue Reconciliation Dashboard — Eko × SBI (V60)

An enterprise-style React frontend for CSP-wise and transaction-type-wise commission reconciliation.

## What is included
- KPI cards for successful transactions, transaction amount, expected/actual commission, net shortfall and reconciliation rate
- Date/CSP/transaction-type/status filters
- Search
- Expected vs Actual daily commission trend
- Reconciliation status donut
- CSP-wise reconciliation table
- Transaction-type-wise commission analysis
- AI reconciliation insight panel
- Exception queue with severity and status
- Responsive layout
- Deterministic-financial-calculation principle in the UI

## Run
```bash
npm install
npm run dev
```

Then open the local Vite URL shown in the terminal.

## Backend integration
The dashboard reads the live FastAPI endpoints. Do not edit sample arrays: the current UI is source-controlled and populated from the uploaded reconciliation result.

## Recommended production integration
Frontend:
React + Tailwind + Recharts

Backend:
Python + FastAPI

Data:
PostgreSQL/MySQL + Pandas/OpenPyXL for CSV/XLSX ingestion

Financial calculation:
Deterministic reconciliation/rule engine — NOT the LLM

AI:
Use the AI layer for column/file understanding, exception grouping, root-cause explanation and natural-language queries. Keep every financial number traceable to source transactions and approved commission rules.

## V14 performance flow
The frontend does not trigger full reconciliation after every file upload. It checks a lightweight source-status endpoint. After all three files validate, reconciliation is started once. Processing pages use a compact backend snapshot, and completed reconciliation pages read the cached deterministic result.


## V60 audit notes
- Dashboard values are backend-driven; there are no demo financial arrays in the UI.
- Expected commission is calculated only by the deterministic backend rule engine.
- Unresolved values are shown as `N/A`; the frontend never invents commission.
- The Transaction Type Mix JSX has been corrected after a Vite parser issue in the previous V60 package.
