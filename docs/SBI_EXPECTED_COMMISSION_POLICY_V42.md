# SBI Expected Commission Control Policy — V42

## Purpose

The project calculates a **verified monthly transaction expected commission** only from deterministic SBI rules. It does not infer a rate from the BC payout.

## Source hierarchy

1. SBI Updated Commission Structure effective 01.04.2025 (PDF) — authoritative published transaction/slab conditions where applicable.
2. SBI CSP Commission Master — normalized rule catalog created for this project; preserves status such as Confirmed, Mapping to confirm, To confirm and Value missing.
3. Product-wise commission workbook — supplementary product mapping/average information. Product averages are **not** substituted for PDF slab/percentage rules.

## Calculation states

- **OK / Verified**: exactly one confirmed SBI rule applies and all required transaction conditions are available.
- **CONDITIONAL**: rule exists but geography, commercial evidence, approval status, customer-fee evidence, or another required condition prevents final verification.
- **CONDITION FAIL**: the transaction amount/date falls outside every applicable SBI rule/slab.
- **UNMAPPED**: no exact operational-to-SBI commercial mapping exists.

## Monthly expected amount

`Verified Monthly Expected Transaction Commission = SUM(expected commission for OK rows only)`

Conditional, provisional and unmapped rows are not silently included.

Monthly incentives, reimbursements and penalties are separate commercial components. They require their own evidence and are not inferred from transaction rows.

## Important SBI examples

- Cash Withdrawal, Cash Deposit and Remittance (Cash) use the stated amount slabs and apply from Rs 100; amounts above Rs 30,000 have no stated rate in the supplied schedule. Do not extrapolate.
- STDR/FD is 0.50% of amount deposited with rural/urban transaction limits and commission caps.
- IMPS is fee-based: customer fee formula/floor/cap followed by CSP share and CSP commission floor/cap.
- Rural CSP incentive requires the stated login/activity conditions; it cannot be derived from transaction count alone.
- Women CSP, m-ATM and TAB incentives have CSP-level monthly caps and require channel/status evidence.
- Inactivity penalty is not derived from zero transactions; inactivity/onboarding evidence is required.

## No silent assumptions

The engine never:

- chooses Rural or Urban when the source does not identify the CSP geography;
- treats a product average as a per-transaction rate when the SBI PDF supplies a slab;
- extrapolates a rate above a published maximum transaction amount;
- treats a count mismatch as a penalty;
- uses actual BC commission to reverse-engineer an expected rate;
- treats a provisional `Mapping to confirm` rule as a final settlement rule.
