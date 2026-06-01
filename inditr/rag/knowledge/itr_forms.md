# ITR Form Selection — AY 2026-27

## ITR-1 (Sahaj) — Eligibility

ITR-1 is the simplest form for resident individual filers with straightforward income.

### Who CAN file ITR-1 (all conditions must be met)
- Resident individual (not NRI, not HUF, not company)
- Total income up to ₹50,00,000
- Salary income and/or pension
- Up to **two house properties** (self-occupied, let-out, or deemed let-out) — AY 2026-27 expansion
- Income from other sources (interest, dividends) — except winnings from lottery, horse racing, etc.
- Agricultural income up to ₹5,000
- LTCG under Section 112A up to ₹1,25,000 with **no brought-forward CG losses** — AY 2026-27 expansion

### Who CANNOT file ITR-1
- Has capital gains (STCG or LTCG) OTHER than 112A ≤ ₹1.25L
- Director in a company during FY 2025-26
- Held unlisted equity shares at any time during the year
- Has income from business or profession (even hobby income)
- Has foreign assets or foreign income
- Has brought-forward losses under capital gains head
- Claimed deduction under Section 90/90A/91 (DTAA)
- Has income from more than 2 house properties
- Has STCG under 111A (equity)
- Is an NRI or RNOR

## ITR-2 — Eligibility

For individuals and HUFs with income from capital gains, multiple properties, foreign assets.

### Who MUST file ITR-2
- Has any capital gains (STCG 111A, LTCG 112A, property gains, debt MF gains)
- Has LTCG 112A exceeding ₹1,25,000 (even without other CG)
- Has income from more than 2 house properties
- Is a director in a company
- Holds unlisted equity shares
- Is an NRI or RNOR
- Has foreign assets, foreign income, or DTAA claims
- Has brought-forward capital loss to be set off
- Total income exceeds ₹50 lakh (even if only salary — if director or has unlisted equity)

## ITR-3 — Business/Profession Income

For individuals with income from business or profession (proprietary firms, freelancers).
Also required if partner in a firm. Not covered by IndITR (target is salaried filers).

## Key Decision Logic Used by IndITR

At intake, IndITR uses a conservative routing rule:
- If income sources include `capital_gains` → ITR-2 (safe default; actual amounts unknown at intake)
- If income sources include only `salary`, `house_property` (≤2), `other_sources` → ITR-1
- `house_property` alone no longer forces ITR-2 since AY 2026-27 expanded ITR-1 eligibility
- STCG (111A) always → ITR-2, even if small

## Pre-filled Data Sources

### AIS (Annual Information Statement)
- Comprehensive view of all income sources reported to IT department
- Covers: TDS, TCS, capital gains, dividends, interest, rental income, foreign remittances
- Available on incometax.gov.in → Services → Annual Information Statement

### Form 26AS
- TDS/TCS credit statement
- Includes advance tax paid, self-assessment tax paid
- Now part of AIS; separate 26AS form available via IT portal

### Form 16 (Salary)
- Part A: TDS details (quarterly TDS deducted)
- Part B: Salary breakdown, employer PAN/TAN, deductions under Chapter VI-A
- Issued by employer by 15 June of the assessment year

## Filing Deadlines — AY 2026-27

| Category                          | Due Date              | Notes |
|-----------------------------------|-----------------------|-------|
| Individuals (non-audit)           | **31 July 2026**      | Standard deadline |
| Individuals requiring audit       | 31 October 2026       | |
| Revised return                    | **31 March 2027**     | Budget 2026 extended from Dec 31, 2026 |
| Belated return (with penalty)     | **31 March 2027**     | Budget 2026 extended from Dec 31, 2026 |

**Budget 2026 extension**: The revised and belated return deadline for AY 2026-27 was extended by Budget 2026 from December 31, 2026 to **March 31, 2027**. A nominal late fee applies when filing the revised return after December 31:
- ₹1,000 if total income ≤ ₹5,00,000
- ₹5,000 if total income > ₹5,00,000

Late filing fee under Section 234F (for belated original returns filed after July 31, 2026):
- ₹1,000 if total income ≤ ₹5,00,000
- ₹5,000 if total income > ₹5,00,000
