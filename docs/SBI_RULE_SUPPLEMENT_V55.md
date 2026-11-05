# V55 — SBI Product Rule Supplement

## Source

The following rules are taken directly from the SBI commission-rule screenshots supplied by the user in this chat. They are stored as a deterministic rule supplement and do not use historical BC payouts to infer rates.

## Account Opening — PMJDY

| Ref | Condition | Rate |
|---|---|---:|
| CM001 | With e-KYC: initial deposit >= Rs 1000 | Rs 50 |
| CM002 | With e-KYC: initial deposit >= Rs 500 to < Rs 1000 | Rs 40 |
| CM003 | With e-KYC: initial deposit >= Rs 100 to < Rs 500 | Rs 30 |
| CM004 | With e-KYC: initial deposit < Rs 100 including zero balance | Rs 20 |
| CM005 | Without e-KYC, with OVD: initial deposit >= Rs 100 | Rs 10 |
| CM006 | Without e-KYC, with OVD: initial deposit < Rs 100 including zero balance | Rs 5 |

### KYC control

The transaction source must contain explicit KYC/OVD evidence to select CM001-CM006. If KYC evidence is absent or ambiguous, the transaction is **CONDITIONAL** and expected commission is not fabricated.

The current August Success Transaction source has no usable KYC field. Therefore its 4,077 Initial Deposit transactions remain conditional until KYC evidence is supplied.

## Social Security

| Ref | Product | Condition | Commission |
|---|---|---|---:|
| CM002 | PMJJBY | Q1 (June-July-August), premium Rs 436 | Rs 30 |
| CM002 | PMJJBY | Q2 (Sep-Oct-Nov), premium Rs 342 | Rs 22.50 |
| CM002 | PMJJBY | Q3 (Dec-Jan-Feb), premium Rs 228 | Rs 15 |
| CM002 | PMJJBY | Q4 (March-Apr-May), premium Rs 114 | Rs 7.50 |
| CM003 | PMSBY | Age 18-70, cover Rs 2 lakh, premium Rs 20/year | Rs 1 |

These values supersede older V54 supplement values for Q2 and Q4 because the latest user-supplied screenshot explicitly shows Rs 22.5 and Rs 7.5.

## August 2026 source impact

- Initial Deposit: all rows → conditional because KYC evidence is absent.
- PMJJBY: 41 August enrollments × Rs 30 = Rs 1,230.
- PMSBY: 54 enrollments × Rs 1 = Rs 54.

No amount is calculated for an account-opening row merely because its amount falls into an e-KYC slab when the source does not establish e-KYC.
