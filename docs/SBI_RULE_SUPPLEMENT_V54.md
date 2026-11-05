# V54 — SBI Product Rule Supplement

This supplement records the SBI commission rule supplied by the project owner in the chat on 2026-10-01.

## Rules added/confirmed

### Account Opening (PMJDY)
- Initial deposit >= Rs. 1000 -> Rs. 50
- Initial deposit >= Rs. 500 and < Rs. 1000 -> Rs. 40
- Initial deposit >= Rs. 100 and < Rs. 500 -> Rs. 30
- Initial deposit < Rs. 100 (including zero balance) -> Rs. 20

### PMJJBY
- Q1 (June-July-August) -> Rs. 30 per enrollment
- Q2 (September-October-November) -> Rs. 23 per enrollment
- Q3 (December-January-February) -> Rs. 15 per enrollment
- Q4 (March-April-May) -> Rs. 8 per enrollment

### PMSBY
- Rs. 1 per enrollment

## Calculation policy

- These rules replace older copies of the same PMJDY/PMJJBY/PMSBY rules in the consolidated master so duplicate same-priority rules cannot create ambiguity.
- `INITIAL DEPOSIT` is classified by transaction amount.
- `CUSTOMER ENROLL FOR SSS` is classified as PMSBY/PMJJBY using the deterministic premium + month mapping already present in the project.
- Unknown SSS premium values remain UNMAPPED; the system does not guess.
- Expected commission is calculated from this rule supplement and is never inferred from the BC report's actual commission.
- The supplied source does not provide a separate customer-age/eligibility field; the calculation therefore represents the supplied product-rule calculation for identifiable enrollment transactions, not an independent eligibility certification.
