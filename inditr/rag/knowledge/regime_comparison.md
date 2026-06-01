# Old vs New Tax Regime — Choosing the Right One

## Core Difference

New regime: lower slab rates, almost no deductions, ₹75K standard deduction only.
Old regime: higher slab rates but allows many deductions that can significantly reduce taxable income.

## When New Regime is Better

New regime is almost always better for:
- Young earners with low deductions (no home loan, no HRA claim, low investments)
- Those earning ≤ ₹12,00,000 — zero tax due to 87A rebate
- Anyone whose total deductions (80C + 80D + HRA + home loan) are less than the regime advantage

## When Old Regime is Better

Old regime can save more tax if the filer has substantial deductions:
- Home loan interest (up to ₹2,00,000 Section 24b)
- Full 80C (₹1,50,000) + NPS 80CCD(1B) (₹50,000)
- HRA exemption (especially metro cities with high rent)
- 80D health insurance

Rule of thumb: old regime beats new regime only when total deductions exceed approximately:
- For ₹15L income: need ~₹3,75,000 in deductions for parity
- For ₹20L income: need ~₹3,75,000+ in deductions
- Standard deduction difference of ₹25,000 already favours new regime

## Break-Even Analysis

At any income level, the break-even deduction amount is:
Break-even deductions = (New Regime Tax − Old Regime Tax before deductions) ÷ Marginal Tax Rate

IndITR's engine computes this exactly using compare_regimes() on the actual data.

## Regime Switch Rules

- Salaried employees can switch between regimes every year at the time of filing
- Those with business/profession income: can switch from old to new only once (then locked)
- Regime must be declared to employer at the start of the year for TDS purposes
- Employee can choose a different regime at filing time if different from employer declaration — but must pay any shortfall

## Available Deductions by Regime

| Deduction / Exemption        | Old Regime | New Regime |
|------------------------------|------------|------------|
| Standard Deduction           | ₹50,000    | ₹75,000    |
| Section 80C                  | Yes (₹1.5L)| No         |
| Section 80CCD(1B) NPS        | Yes (₹50K) | No         |
| Section 80CCD(2) employer NPS| Yes (14%)  | Yes (14%)  |
| Section 80D health insurance | Yes        | No         |
| HRA Exemption Section 10(13A)| Yes        | No         |
| Home Loan Interest Section 24b| Yes (₹2L) | No         |
| 80TTA/TTB interest           | Yes        | No         |
| Section 80E education loan   | Yes        | No         |
| Section 80G donations        | Yes        | No         |
| LTA Leave Travel Allowance   | Yes        | No         |
| HP Loss set-off (₹2L cap)    | Yes        | No         |
| 87A Rebate threshold         | ₹5,00,000  | ₹12,00,000 |

## Impact of Capital Gains on Regime Choice

Capital gains (111A STCG, 112A LTCG) are taxed at flat rates independent of regime:
- The regime choice affects only regular income (salary, other sources)
- High capital gains with low salary: new regime almost always wins (flat rates unaffected)
- Capital gains do NOT benefit from old regime deductions (deductions reduce only normal income)

## Employer Declaration Timing

- Employee must inform employer of regime choice at the start of the financial year
- If no declaration: employer defaults to new regime for TDS computation
- If old regime chosen but investments not done by March: employer deducts additional TDS in Q4
- Proof of investments (Form 16 Part B) must align with actual investments made
