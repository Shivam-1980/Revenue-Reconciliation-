# Transaction Type Mapping Source

Controlled source: `Transaction_Type_Mapping.xlsx` supplied for the August 2026 reconciliation review.

Mapping confidence used by the project:
- `EXACT`: direct name/operational mapping from the supplied mapping sheet.
- `PROBABLE`: matched by meaning and similar volume; allowed for calculated expected revenue but not silently treated as an approved business mapping.
- `CONDITIONAL`: product can be classified/calculated from the successful source, but additional evidence or BC equivalence is required.
- `UNMAPPED`: no approved BC transaction-type mapping.

Special controls:
- `Initial deposit` is classified into the four account-opening slabs for SBI rule calculation and mapped to the corresponding BC slab categories for source-count control.
- `Customer enroll for SSS` is classified to PMJJBY/PMSBY for SBI expected-revenue calculation, but it is **not** joined to BC PMJJBY/PMSBY service rows because the supplied mapping sheet marks it as having no equivalent BC transaction type.
- `PPF SSA TXN` and `AEPS OFFUS Fund Transfer` remain unmapped.
