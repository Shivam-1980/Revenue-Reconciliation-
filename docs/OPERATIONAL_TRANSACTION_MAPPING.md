# Operational Transaction Mapping — SBI Revenue Reconciliation V25

This mapping is derived from the supplied August successful-transaction file, the supplied CSP-wise transaction-type commission report, and the SBI commission master.

## Deterministic mappings

| Source transaction type | BC report transaction type | Basis |
|---|---|---|
| AEPS ONUS Withdrawal | AEPS ONUS WITHDRAWAL | Exact product label; SBI generic Cash Withdrawal slab applied provisionally because master says Mapping to confirm |
| AEPS ONUS Deposit | AEPS ONUS DEPOSIT | Exact product label; SBI generic Cash Deposit slab applied provisionally |
| AEPS ONUS Fund Transfer | AEPS ONUS FUNDTRANSFER - HOME | Exact product label; SBI generic Remittance/Transfer Home slab applied provisionally |
| AEPS OFFUS Withdrawal | AEPS ACQUIRER WITHDRAWAL | Exact operational product label in BC report |
| Withdrawal | CASH WITHDRAWAL | Exact operational cash-withdrawal label |
| Deposit | CASH DEPOSIT | Exact operational cash-deposit label |
| ATM Onus Withdrawal | DEBIT CARD ONUS | Operational source/report label pairing |
| ATM Offus Withdrawal | DEBIT CARD OFFUS | Operational source/report label pairing |
| ATM Deposit | MATM ONUS DEPOSIT | Operational source/report label pairing |
| ATM FUNDSTRANSFER | MATM ONUS FUNDSTRANSFER - HOME | Operational source/report label pairing |
| Fund Transfer | FUNDTRANSFER - HOME | Exact operational label pairing |
| Money Transfer | MONEY TRANSFER | Exact label; Excel-only ₹9 rule |
| Loan Deposit | LOAN DEPOSIT | Exact label; SBI Cash Deposit slab applied provisionally because master says Mapping to confirm |
| IMPS Fund Transfer | IMPS FUNDTRANFER | Exact label; SBI IMPS fee-share rule applied provisionally |
| IMPS Money Transfer | IMPS MONEY TRANSFER | Exact label; SBI IMPS fee-share rule applied provisionally |
| YONO WITHDRAWAL | YONO CASH | Operational label pairing |
| STDR open | STDR OPEN | Exact label |
| BHARAT BILL PAYMENTS | BBPS - ELECTRICITY | Operational label pairing; BBPS source mapping remains To confirm and is not final-settlement comparable |

## Amount-driven splits

### Initial deposit
The successful transaction source has one `Initial deposit` label, while the BC report has four account-opening buckets. The source transaction amount deterministically selects:

- `< ₹100` → `ACC OPEN WITH EKYC AND INIT DEP BELOW 100`
- `₹100–₹499` → `ACC OPEN WITH EKYC AND INIT DEP BTWN 100 AND 499`
- `₹500–₹999` → `ACC OPEN WITH EKYC AND INIT DEP BTWN 500 AND 999`
- `≥ ₹1000` → `ACC OPEN WITH EKYC AND INIT DEP 1000 OR ABOVE`

### Customer enroll for SSS
The August source contains premiums of ₹436 and ₹20:

- ₹436 → `PMJJBY`
- ₹20 → `PMSBY`

No other amount is silently assigned.

## Intentionally unresolved

- `PPF SSA TXN` — no corresponding BC transaction-type category is present in the supplied commission report.
- `AEPS OFFUS FUND TRANSFER` — no corresponding BC transaction-type category is present in the supplied commission report.
- BBPS/other source items marked `To confirm` or `Value missing` are not promoted to final settlement rules.

## Important policy

`Mapping to confirm` rules are calculated as **provisional control values** because the supplied master explicitly provides the generic PDF schedule and the product-level Excel label. They are **not treated as final settlement-approved rules** until the mapping is formally confirmed. No transaction actual is used to infer a rate.
