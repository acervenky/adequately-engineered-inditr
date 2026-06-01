<div align="center">

# IndITR

### *The Tax Agent That Doesn't Let AI Do The Math*

**Part of the *Adequately Engineered by Venky* Series**

> *Welcome to "Adequately Engineered by Venky" — a collection of projects where the problem is real, the stack is boring, and the thing actually works. No LLMs doing arithmetic. No Kubernetes for a side project. No blockchain anywhere. Just the right tool, the right amount of it, and software that ships before the July 31 deadline. Every project in this series exists because "I was personally annoyed by this problem and decided to fix it properly." Style points? Optional. Working in production? Mandatory.*

[![AY](https://img.shields.io/badge/Assessment_Year-2026--27-blue?style=for-the-badge)](#)
[![ITR](https://img.shields.io/badge/Forms-ITR--1_%7C_ITR--2-green?style=for-the-badge)](#)
[![Engine](https://img.shields.io/badge/Tax_Engine-Zero_LLM-red?style=for-the-badge)](#)
[![Framework](https://img.shields.io/badge/Runtime-LangGraph-purple?style=for-the-badge)](https://langchain-ai.github.io/langgraph/)
[![Tests](https://img.shields.io/badge/Tests-301_passing-brightgreen?style=for-the-badge)](#)
[![License](https://img.shields.io/badge/License-CC%20BY--NC%204.0-yellow?style=for-the-badge)](https://creativecommons.org/licenses/by-nc/4.0/)

**Assessment Year:** AY 2026-27 &nbsp;|&nbsp; **ITR Forms:** ITR-1 and ITR-2 &nbsp;|&nbsp; **Filing Window:** Apr 1 – Jul 31, 2026

</div>

---

> **⚠️ DISCLAIMER:** IndITR is an open-source tool for tax preparation assistance. It **does not** constitute professional tax advice. All computations must be verified by the user before filing. The authors assume no liability for errors, omissions, or penalties arising from use of this tool. When in doubt, consult a qualified Chartered Accountant (CA).

---

> **🔒 YOUR DATA STAYS WHERE YOU PUT IT:** IndITR runs on any LLM — including a fully local one. Use [Ollama](https://ollama.com) and your Form 16, bank statements, and capital gains never leave your machine. No account. No API key. No cloud. Your financial data is yours.

---

## 📖 Background

Every year, around the third week of July, the same panic sets in across millions of Indian households.

Your employer dropped Form 16 in your inbox on June 15. You've been staring at it since. You downloaded the Zerodha P&L CSV because you bought some ELSS in January and sold some random midcap stock in October. You have no idea if that's STCG or LTCG or slab-rate or something that Budget 2024 changed. Your CA quoted ₹4,500 for "basic filing with capital gains." ClearTax is asking you to upgrade to Pro. TaxBuddy sent you a push notification at 11 PM. The IT portal is timing out.

And somewhere in the back of your mind: *I'm a software engineer. I build systems that handle millions of users. Why can I not file my own taxes?*

The answer is that Indian income tax is **genuinely hard.** Not "hard" like rocket science, but "hard" like a decade of accumulated amendments, two parallel tax regimes with different trade-offs, capital gains rules that changed three times in eighteen months, and a 200-page ITR form for what is essentially salary + some stocks. The complexity is real.

And then there's the other problem: every tool you reach for wants your data. Your Form 16. Your bank statements. Your capital gains. Your PAN. You're handing over everything, to a server you don't control, running a model you can't audit, owned by a company whose privacy policy you didn't read.

So I built IndITR. Not because filing taxes needed AI. Because it needed a correct, deterministic, auditable engine — one that runs on your machine, with a model you choose, where your financial data goes exactly where you tell it to and nowhere else. So I never had to open ClearTax again.

---

## 🆚 The Problem vs. The Adequate Solution

**The Obvious (Wrong) Solution:** Feed your Form 16 to ChatGPT and ask it to compute your tax. Watch it hallucinate a ₹12,000 surcharge on a ₹9L income. Trust it anyway because it sounds confident.

**The Venky Solution:** Build a pure Python tax engine with zero LLM involvement — hardcoded slabs, tested surcharge brackets, verified 87A rebate logic, deterministic capital gains aggregation. Then wrap it in a conversational LLM layer that handles *only* what LLMs are actually good at: extracting structured data from unstructured documents (Form 16 PDFs, broker Excel exports) and chatting with you about your finances. The LLM collects data. Python computes tax. These two things never switch roles.

Because the moment an LLM touches a number, that number is a guess.

---

## 🏗️ The Four-Act Pipeline

IndITR is a LangGraph state machine. Every node is a function, every transition is a compiled edge, every state change is checkpointed to SQLite. Restart the server mid-conversation — the session resumes from exactly where it left off.

```
┌─────────────────────────────────────────────────────────────────┐
│  ACT 1 — INTAKE  (LLM, conversational)                          │
│                                                                  │
│  collect_profile → identify_income_sources →                     │
│  determine_itr_form → build_doc_checklist                        │
│                                                                  │
│  Output: FilerProfile, ITR form (ITR-1 or ITR-2), doc checklist │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  ACT 2 — DOCUMENTS  (parsers + LLM vision fallback)             │
│                                                                  │
│  request_documents → parse_documents → validate_extractions      │
│                           │                                      │
│                    confidence < 0.85?                            │
│                           │                                      │
│                ⏸ INTERRUPT BEFORE: human_doc_review             │
│                (API shows low-confidence fields to user,         │
│                 user corrects, graph resumes)                    │
│                                                                  │
│  Output: ParsedDocument per file, confidence scores             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  ACT 3 — GAP FILL & CROSS-CHECK  (LLM + pure Python loop)       │
│                                                                  │
│  gap_fill_chat → cross_check → aggregate_data                    │
│       ↑__________________|  (critical failure → retry)          │
│                                                                  │
│  Output: ExtractedTaxData (Pydantic-validated, engine-ready)    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  ACT 4 — COMPUTATION & ADVISORY  (pure Python + LLM loop)       │
│                                                                  │
│  compute_tax → build_outputs → tax_advisor ⏸ INTERRUPT AFTER   │
│                                     ↑____________↓              │
│                               (conversation loop)               │
│                    user says "ready to file"                     │
│                               │                                  │
│               ⏸ INTERRUPT BEFORE: human_final_review            │
│               (shows computation summary, waits for confirm)     │
│                               │ confirmed                        │
│                           finalise                               │
│                                                                  │
│  Output: TaxComputation, ITR JSON, PDF, regime recommendation   │
└─────────────────────────────────────────────────────────────────┘
```

The graph runs on a real **LangGraph `SqliteSaver` checkpointer** — not a hand-rolled session store. Every node transition is persisted. `interrupt_before` and `interrupt_after` are real LangGraph primitives, not marker strings in message history.

---

## 🧠 The Core Design Decision

The most important line in this entire codebase is in `CLAUDE.md`:

> *LLM is used ONLY for: (a) conversational interview, (b) document parsing/OCR. ZERO LLM calls in: engine/, output_builders/. Every number that enters tax computation must pass through a Pydantic-validated structured extraction first.*

Here is what that means in practice:

**The LLM's job:**
- Ask you friendly questions about your investments, rent, and deductions
- Extract `gross_salary: 1200000` from a 14-page Form 16 PDF
- Classify a Zerodha P&L XLSX and map its columns to the right schema
- Explain why the old regime saves you ₹18,000 this year

**Python's job:**
- Apply the correct tax slab to every rupee of income
- Compute the 87A rebate threshold exactly
- Calculate LTCG above the ₹1,25,000 exemption at 12.5%
- Apply surcharge, cess, marginal relief
- Produce a number that is correct

These two jobs do not overlap. Not even a little.

The LLM has a full suite of **engine-backed tools** it can call — `estimate_tax`, `calculate_hra`, `check_87a_rebate`, `deduction_impact` — so when you ask "what if I invest ₹1L in NPS?", it calls the actual engine with your actual numbers and shows you the actual saving. It does not guess.

---

## ✨ Unique Design Features

### 1. BYOLLM — Bring Your Own LLM

IndITR has zero opinion about which LLM you use. It runs on anything that speaks the OpenAI API format — which is everything, because that became the de-facto standard.

The tax engine is pure Python. The LLM is only used for conversation and document parsing. That means a small local model is completely adequate. You do not need GPT-4. A 7B quantized model running on a laptop CPU handles the gap-fill interview and Form 16 extraction just fine.

**The default is Ollama — free, local, no account, no API key, no data leaving your machine.**

| Provider | `LLM_MODEL` example | Notes |
|---|---|---|
| **Ollama** (local) | `ollama/qwen2.5:latest` | Free. Runs on CPU. `ollama pull qwen2.5`. Default. |
| **LM Studio** (local) | `lm_studio/your-model` | Good for large models on a GPU. |
| **vLLM** (self-hosted) | `openai/mistral-7b-instruct` | Production local deployment. |
| **OpenRouter** (cloud) | `openrouter/google/gemma-3-27b-it` | 300+ models. Free tiers available. |
| **DeepInfra** (cloud) | `deepinfra/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B` | Cost-effective. Used internally by Venky. |
| **OpenAI** (cloud) | `openai/gpt-4o-mini` | Works. Expensive for what it does here. |
| **Anthropic** (cloud) | `anthropic/claude-haiku-4-5-20251001` | Works. Also expensive for parsing Form 16. |

One key file to know: `inditr/graph/llm.py`. That's the single source of truth for all LLM configuration. No model name is hardcoded anywhere else in the codebase.

---

### 2. RAG-Grounded Tax Knowledge

The advisor and gap-fill nodes don't just rely on what the LLM was trained on. Every user message triggers a semantic search over **7 indexed knowledge files** covering every aspect of AY 2026-27 tax law — slabs and rebates, capital gains rules, deductions, TDS thresholds, ITR form eligibility, VDA/crypto, ESOP/RSU, and CA-level tips.

The retrieved chunks are injected into the LLM prompt at every turn as authoritative context. This means the advisor quotes correct CII values, right 54EC timelines, and accurate TDS thresholds — not what the model guesses from training data.

```
User: "Is Section 54EC still available for property sold in FY 2025-26?"

[RAG] → retrieved from capital_gains.md:
      "Section 54EC: LTCG from any immovable property → NHAI/REC bonds.
       Max ₹50,00,000. Within 6 months of sale. 5-yr lock-in."

[LLM] → grounded answer with correct numbers, not a guess
```

The knowledge files are plain Markdown — update a rule, re-run `python scripts/build_rag_index.py`, done. No retraining. No fine-tuning. No model update.

---

### 3. Engine-Backed LLM Tool Suite

The advisor is architecturally incapable of computing a tax number itself. It has a registered set of Python tools that call the actual engine, and it must call them for any number it wants to quote:

| Tool | What it does |
|---|---|
| `estimate_tax` | Full `compare_regimes()` run — both regimes, exact liability |
| `calculate_hra` | Section 10(13A) three-condition HRA exemption |
| `check_87a_rebate` | Eligibility + amount + CG caveat (111A/112A excluded) |
| `deduction_impact` | Before/after comparison for any 80C/80D/NPS investment |

When you ask *"what if I start paying health insurance of ₹25,000?"*, the LLM calls `deduction_impact` with your actual gross salary and existing deductions. The engine runs. The LLM gets back: *"Old regime: ₹1,24,800 → ₹1,17,300. Saves ₹7,500."* It reports that. It does not compute it.

This is not just a safety measure — it means the advisor's numbers are the same numbers that will appear in your ITR JSON.

---

### 4. Pydantic as the Statutory Compliance Boundary

The `Deductions` Pydantic model has validators that enforce actual Indian tax law limits:

```python
@field_validator("sec_80c")
def cap_80c(cls, v):
    if v > 150_000.0:
        raise ValueError("80C cannot exceed ₹1,50,000")   # the law

@field_validator("sec_54ec_exemption")
def cap_54ec(cls, v):
    if v > 5_000_000.0:
        raise ValueError("54EC cannot exceed ₹50,00,000")  # Section 54EC limit
```

Every deduction has a cap. Every cap is sourced from the Finance Act. The engine cannot receive a legally impossible input — not from a bug, not from a hallucinating LLM, not from a malformed API call. If the data doesn't conform to the law, it doesn't reach computation.

---

### 5. Confidence-Gated Document Validation with Cross-Check Promotion

The document validation system has three confidence tiers, designed to minimise unnecessary human interruptions while catching real problems:

```
LLM extraction result (base confidence: 0.80)
         │
         ▼
   Python cross-checks:
   - PAN format: AAAAA9999A ✓
   - TAN format: AAAA99999A ✓
   - Arithmetic: net_salary = gross − std_ded − prof_tax − HRA ✓
   - Statutory: 80C ≤ 1.5L, standard deduction ≤ 75K ✓
   - Part A vs Part B TDS: within ±2% ✓
         │
         ▼
   PASS → confidence promoted to 0.92 → skips human review
   FAIL → field flagged → human_doc_review interrupt fires

TRACES regex fallback (when LLM unavailable):
   → assigned confidence 0.90 → skips human review
   → system never silently returns zeros
```

The 0.85 threshold is the gate. 0.92 (cross-check pass) and 0.90 (regex fallback) are both above it. Only genuinely uncertain or arithmetically inconsistent fields interrupt the user.

---

### 6. Bank-Agnostic Statement Parsing

Most bank statement parsers are a lookup table: HDFC gets regex A, SBI gets regex B, Canara isn't supported. This one has no such table.

The parser uses a targeted 3-LLM-call pipeline that works on any Indian bank e-statement:

1. Extract full text with pdfplumber (free)
2. Python greps for `NEFT CR` lines — an RBI-mandated format used by every scheduled bank
3. **LLM call 1** — page-1 header + those NEFT lines → identifies employer name (e.g. `"ACMECORP"`), bank name, account period
4. Python greps for that employer name → collects only the matching context windows (~5KB, not the full document); repeats for broker names and FD/interest keywords
5. **LLM call 2** — employer context blocks → structured `(date, amount)` per salary entry
6. **LLM call 3** — interest blocks → structured interest entries
7. Python filters to keep only entries whose description matches the employer

Zero bank-specific code. The LLM reads whatever header format, column naming, or reference style the bank uses — and adapts. Adding Canara Bank support required no code; testing on a 131-page e-passbook worked out of the box.

---

### 7. Simultaneous Dual-Regime Computation

`compare_regimes()` runs both Old and New regime with identical inputs in a single call. The recommendation is the exact computed tax liability difference — not a heuristic, not a rule of thumb, not "new regime is usually better for income below X."

```python
old = _compute_regime(data, filer, "old")   # full computation
new = _compute_regime(data, filer, "new")   # full computation, same inputs

savings = abs(old.total_tax_liability - new.total_tax_liability)
# This number is exact. It accounts for your specific deductions,
# your specific capital gains, your age, your TDS. Not an approximation.
```

The what-if engine extends this: any hypothetical change (invest more in NPS, claim 54EC bonds, switch regime) re-runs `compare_regimes()` with the modified inputs and returns the new exact difference. The advisor never estimates savings. It always shows exact savings.

---

## 📄 Supported Documents

### ✅ Form 16 — TDS Certificate (PDF)

The primary document. Both TRACES-generated Part A and employer-generated Part B are supported.

**Two-stage extraction:**
1. LLM reads the full PDF and extracts all fields into a structured schema
2. If the LLM fails (bad API key, timeout, rate limit) — a deterministic TRACES-format regex extractor kicks in automatically, assigned confidence 0.90

The system **never silently returns zeros.** It either extracts or logs a `parse_error` with the exact field that failed.

| Field | Source |
|---|---|
| Employer name, TAN | Part A |
| Employee name, PAN | Part A |
| Gross salary (Section 17(1)) | Part B |
| HRA exemption (Section 10(13A)) | Part B |
| Standard deduction (Section 16(ia)) | Part B |
| Professional tax (Section 16(iii)) | Part B |
| Chapter VI-A deductions (80C, 80CCD(1B), 80CCD(2), 80D, 80E, 80G, 80TTA/TTB) | Part B |
| TDS deducted by employer | Part B |

---

### ✅ Zerodha Tax P&L (XLSX / CSV / PDF)

**XLSX (primary):** Multi-sheet workbook `taxpnl-CLIENTID-YYYY_YYYY.xlsx`

| Sheet | What is extracted |
|---|---|
| Equity | STCG total, LTCG total |
| Mutual Funds | MF STCG, MF LTCG |
| Tradewise Exits | Per-trade: ISIN, buy/sell dates, gain, asset type |

Every ISIN is classified at parse time using scheme-name keyword matching against 20+ debt-fund terms (liquid, overnight, gilt, FMP, corporate bond, etc.). Post-April 2023 debt MF gains are slab-taxed per Finance Act 2023 — misclassifying them as equity would underreport your tax by real money. A backup keyword check runs again inside `aggregate_data` as defense-in-depth.

---

### ✅ Upstox Realized P&L (XLSX)

File: `realizedPnL_EQ_YYYY-MM-DD_To_YYYY-MM-DD_CLIENTID.xlsx`. Extracts per-trade rows from row 27 onwards. Same ISIN-based classification as Zerodha. Speculation (intraday) trades are excluded from capital gains.

---

### ✅ Bank Statements (PDF) — any Indian bank
Used to cross-check salary credits against Form 16 gross salary (±2% tolerance) and to capture FD interest (80TTA/80TTB) and broker payouts.

Works with any bank that produces a native-text PDF (downloaded from net banking) — no bank-specific configuration required. The parser uses a targeted 3-LLM-call pipeline: it greps all NEFT credit lines (an RBI-mandated standard format), asks the LLM to identify the employer from that list, then greps only the matching context windows (~5KB instead of the full document) for structured extraction. The LLM adapts to any column layout, any bank header format, and any employer name automatically.

Extracts: salary credits (with date and amount), broker payouts (Zerodha, Upstox, Angel One, etc.), FD/savings bank interest.

**Input requirement:** native-text PDF downloaded from your bank's internet banking portal. Scanned or photographed documents cannot be processed — use the digital download.

---

### ⚠️ Vision Fallback (Everything Else)
Form 26AS, AIS, NPS PRAN statements, CAMS/KFintech MF statements, home loan certificates — identified but extracted via vision model (lower confidence, triggers human review gate).

---

## 💰 Tax Rules Embedded in the Engine (AY 2026-27)

All rules are hardcoded in `inditr/engine/` — pure Python, no LLM, 301 tests. Covers every Budget from 2024 through 2026.

### New Regime Slabs (default from FY 2024-25)
| Income slab | Rate |
|---|---|
| Up to ₹4,00,000 | 0% |
| ₹4,00,001 – ₹8,00,000 | 5% |
| ₹8,00,001 – ₹12,00,000 | 10% |
| ₹12,00,001 – ₹16,00,000 | 15% |
| ₹16,00,001 – ₹20,00,000 | 20% |
| ₹20,00,001 – ₹24,00,000 | 25% |
| Above ₹24,00,000 | 30% |

Standard deduction: **₹75,000** &nbsp;|&nbsp; 87A rebate: income ≤ ₹12,00,000 → zero tax (max rebate **₹60,000**)

### Old Regime
Age-based slabs (age as of 31-Mar-2026). General / Senior (≥60) / Super Senior (≥80).

Standard deduction: **₹50,000** &nbsp;|&nbsp; 87A rebate: income ≤ ₹5,00,000 → max **₹12,500**

### Capital Gains (Budget 2024 — unchanged in Budget 2025 and Budget 2026)
| Asset | Gain type | Rate |
|---|---|---|
| Listed equity / equity MF | STCG (Sec 111A) | **20%** |
| Listed equity / equity MF | LTCG (Sec 112A) | **12.5%** — ₹1,25,000 annual exemption |
| Debt MF (post-Apr-2023 purchase) | Any | **Slab rate** (Sec 50AA) |
| Property (post-Jul-23-2024 acquisition) | LTCG | **12.5%** (no indexation) |
| Property (pre-Jul-23-2024 acquisition) | LTCG | Lower of: 20%+indexation OR 12.5% flat — engine picks best |
| Share buyback (FY 2025-26+) | STCG / LTCG | Same as listed equity |
| VDA / Crypto | Any | **30%** flat (Sec 115BBH) — no loss set-off |

87A rebate does **not** apply to Sections 111A, 112A, or VDA (115BBH) — Finance Act 2025 expressly bars this.

### Capital Gains Reinvestment Exemptions (both regimes)
| Section | From → To | Limit | Deadline |
|---|---|---|---|
| **54** | Residential house → new house | Full LTCG | Buy within 2 yrs / construct within 3 yrs |
| **54EC** | Any property → NHAI/REC bonds | ₹50,00,000 | Within 6 months of sale |
| **54F** | Non-residential asset → house | Proportional | Buy within 2 yrs / construct within 3 yrs |

### Deductions Supported
| Deduction | Old Regime | New Regime |
|---|---|---|
| Standard deduction | ₹50,000 | ₹75,000 |
| 80C (ELSS/PPF/LIC/EPF etc.) | ₹1,50,000 | ❌ |
| 80CCD(1B) employee NPS | ₹50,000 extra | ❌ |
| 80CCD(2) employer NPS | 14% of salary (Budget 2025) | ✅ 14% of salary |
| 80D health insurance | ₹25K self + ₹25K–₹50K parents | ❌ |
| HRA exemption (Sec 10(13A)) | Min of 3 conditions | ❌ |
| Home loan interest (Sec 24b) | ₹2,00,000 cap | ❌ |
| 80E education loan interest | Full interest, 8 years, no cap | ❌ |
| 80G donations | 50–100% of eligible amount | ❌ |
| 80TTA savings bank interest | ₹10,000 | ❌ |
| 80TTB senior bank interest | ₹50,000 | ❌ |
| Sec 54 / 54EC / 54F CG exemptions | ✅ | ✅ |

### Budget Changes Applied
**Budget 2025 (FY 2025-26):** New regime slabs, 87A rebate at ₹12L, 80CCD(2) raised to 14% for private sector, Sec 194A TDS threshold ₹40K→₹50K, Sec 194 dividend threshold ₹5K→₹10K, Sec 194-IB rent TDS 5%→2%, share buyback taxed as CG.

**Budget 2026 (AY 2026-27 impact only):** Revised/belated return deadline extended to **March 31, 2027** (from Dec 31, 2026). Tax slabs, CG rates, and deduction limits are unchanged for AY 2026-27.

**CII FY 2025-26 = 376** (CBDT notified July 1, 2025). Used for pre-Jul-23-2024 property indexation.

---

## 🤝 The Tax Advisor

After computation, IndITR switches into advisory mode. The advisor never guesses — every tip is backed by a live engine call with your actual numbers.

Here's what goes through its head after computing your tax:

```
[ADVISOR] COMPUTATION COMPLETE: New regime saves ₹18,420 for this filer.
          Recommended: NEW regime. Total tax: ₹1,24,800.

[ADVISOR] TIP 1 — 80C headroom: ₹40,000 unused. Maxing it saves ₹12,000 under old regime.
          But old regime still ₹6,420 worse than new even with max 80C.
          → "You need ₹1,85,000+ in total deductions for old regime to beat new. Not worth it."

[ADVISOR] TIP 2 — LTCG harvesting: ₹78,000 of ₹1,25,000 annual equity exemption unused.
          → "Book up to ₹47,000 more in long-term equity gains tax-free. Sell + rebuy."

[ADVISOR] TIP 3 — No health insurance detected.
          → "₹25K 80D deduction available. Buy it young — premiums only go up."

[ADVISOR] TIP 4 — Net payable: ₹12,400. CG income detected.
          → "This may not be covered by salary TDS. Pay via Challan 280 before filing
             to avoid Section 234B interest (~1%/month from April 1)."

[ADVISOR] WHAT-IF: User asked "what if I invest 50L in 54EC bonds?"
          → Running engine with sec_54ec_exemption=5000000...
          → Property LTCG tax: ₹3,12,500 → ₹0. Saves ₹3,12,500. Go do it within 6 months.
```

What-if scenarios the advisor can run in real-time: `sec_80c_delta`, `sec_80d_delta`, `sec_80ccd_1b_delta`, `hra_exemption_delta`, `home_loan_interest_delta`, `sec_80e_delta`, `sec_80g_delta`, `sec_54_exemption_delta`, `sec_54ec_exemption_delta`, `sec_54f_exemption_delta`.

---

## 🛠️ Tech Stack

| Component | Tech | Why this, not something fancier |
|---|---|---|
| API framework | FastAPI | Standard choice. Auto-generates docs. Works. |
| State machine | LangGraph | Proper interrupt/resume semantics. SqliteSaver for free. |
| State persistence | SQLite (SqliteSaver) | One file. Zero ops. Crash-safe. |
| LLM abstraction | LiteLLM | Any OpenAI-compatible endpoint. No provider lock-in. |
| PDF extraction | pdfplumber | Deterministic table/text extraction. Reliable on Form 16. |
| Data validation | Pydantic v2 | Every number is validated before it touches the engine. |
| PDF generation | ReportLab | Generates watermarked DRAFT PDFs. Simple. |
| Local embeddings | BAAI/bge-small-en-v1.5 | ~130MB, runs on CPU, no API key needed. |
| Vector store | zvec | Minimal local vector search for RAG. |
| Tax engine | Pure Python | No database. No ORM. No dependencies. Deterministic. |
| Tests | pytest | 301 tests. >85% coverage on engine/ and parsers/. |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- An LLM — local (Ollama) or cloud (OpenRouter, DeepInfra, OpenAI)

### 1. Install

```bash
git clone https://github.com/acervenky/adequately-engineered-inditr.git
cd adequately-engineered-inditr

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\Activate.ps1

pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env
```

Fastest start — **Ollama** (free, local, no account, no data leaving your machine):

```bash
ollama pull qwen2.5    # main model (~4.7 GB)
ollama pull llava      # vision fallback for scanned PDFs
```

```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=ollama/qwen2.5:latest
LLM_VISION_MODEL=ollama/llava:latest
```

Or use any OpenAI-compatible provider:

```env
# ── OpenRouter (cloud, free tiers, 300+ models) ───────────────────────────────
# LLM_API_KEY=sk-or-v1-...
# LLM_MODEL=openrouter/google/gemma-3-27b-it:free
# LLM_VISION_MODEL=openrouter/google/gemma-3-27b-it

# ── DeepInfra (cloud, cost-effective) ────────────────────────────────────────
# LLM_BASE_URL=https://api.deepinfra.com/v1/openai
# LLM_API_KEY=your-deepinfra-key
# LLM_MODEL=deepinfra/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B

# ── OpenAI ────────────────────────────────────────────────────────────────────
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_API_KEY=sk-...
# LLM_MODEL=openai/gpt-4o-mini
```

The vision model (`LLM_VISION_MODEL`) is only needed as a fallback for scanned PDFs. If you only have text-layer PDFs, set it to the same value as `LLM_MODEL` — it will never be called.

### 3. Build the RAG index (once)

```bash
python scripts/build_rag_index.py
```

Downloads `BAAI/bge-small-en-v1.5` (~130 MB) and indexes the tax knowledge base. Re-run after editing any file in `inditr/rag/knowledge/`.

### 4. Start

```bash
uvicorn inditr.api.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)

### 5. Test

```bash
pytest                                           # all 301 tests
pytest --cov=inditr --cov-report=term-missing   # with coverage
pytest tests/test_engine/ -v                    # engine only
```

---

## 🔌 API Walkthrough

```bash
# 1. Start a session — agent greets you and asks for your details
curl -X POST http://localhost:8000/session/start \
  -H "Content-Type: application/json" \
  -d '{"assessment_year": "AY2026-27"}'
# → {"session_id": "abc123", "message": "Hi! I'm IndITR. What's your name and PAN?"}

# 2. Chat — each message resumes the LangGraph agent from the checkpoint
curl -X POST http://localhost:8000/session/abc123/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Rahul Verma, PAN AAAAA0000A, DOB 01-01-1990, salaried"}'

# 3. Upload Form 16 (parsed immediately via pdfplumber + LLM, stored in graph state)
curl -X POST http://localhost:8000/session/abc123/upload \
  -F "file=@/path/to/form16_partb.pdf"

# 4. Upload Zerodha P&L (if you have capital gains)
curl -X POST http://localhost:8000/session/abc123/upload \
  -F "file=@/path/to/taxpnl-ZV1234-2025_2026.xlsx"

# 5. Check where the agent is
curl http://localhost:8000/session/abc123
# → {"current_act": "gap_fill_chat", "interrupted_at": [], "itr_form": "ITR-2"}

# 6. Confirm after human_final_review interrupt (agent waits here before filing)
curl -X POST http://localhost:8000/session/abc123/confirm \
  -H "Content-Type: application/json" \
  -d '{"confirmed": true}'

# 7. Get your outputs (inline JSON + regime report)
curl http://localhost:8000/session/abc123/outputs
# → ITR JSON (full deduction schedule + CG schedule), regime report, PDF path

# 8. Download files
# PDF summary with portal filing walkthrough (10 pre-filled steps):
curl -OJ http://localhost:8000/session/abc123/download/pdf

# ITR JSON in IT Dept AY 2026-27 offline utility format ({"ITR":{"ITR1":{...}}}):
curl -OJ http://localhost:8000/session/abc123/download/itr-json-official

# ITR JSON in IndITR internal format (for records):
curl -OJ http://localhost:8000/session/abc123/download/itr-json
```

---

## 📁 Project Structure

```
inditr/
├── api/                     FastAPI app
│   └── routes/
│       ├── session.py       LangGraph singleton + SqliteSaver, session lifecycle
│       ├── chat.py          POST /message → graph.invoke() + interrupt detection
│       └── upload.py        POST /upload → parse doc, graph.update_state()
│
├── engine/                  Pure Python. Zero LLM. Zero side effects.
│   ├── regime.py            compare_regimes() — the entry point
│   ├── slabs.py             Slabs, 87A rebate, marginal relief, surcharge, cess
│   ├── capital_gains.py     CG aggregation, Sec 74 set-off, Sec 54/54EC/54F
│   └── deductions.py        Chapter VI-A, 80CCD(2), professional tax
│
├── graph/                   LangGraph state machine
│   ├── graph.py             Graph assembly — interrupt_before/after, SqliteSaver
│   ├── nodes/               One file per Act
│   │   ├── intake.py        Act 1: profile collection, ITR form routing
│   │   ├── documents.py     Act 2: parsing orchestration, human_doc_review
│   │   ├── gap_fill.py      Act 3: deduction interview, cross-check, aggregation
│   │   ├── output.py        Act 4: compute, build ITR JSON/PDF, human_final_review
│   │   └── advisor.py       Act 4: CA-level advisory with engine-backed what-ifs
│   ├── edges.py             Conditional routing functions
│   ├── tools.py             Engine-backed LLM tools (estimate_tax, calculate_hra, etc.)
│   └── llm.py               LiteLLM config — BYOLLM
│
├── models/                  Pydantic models
│   ├── state.py             TaxFilingState TypedDict
│   ├── tax_data.py          ExtractedTaxData, CapitalGain, Deductions
│   ├── profile.py           FilerProfile (PAN validation + masking)
│   └── computation.py       RegimeResult, TaxComputation
│
├── parsers/                 Document parsers — never raise, always return ParsedDocument
│   ├── form16.py            LLM extraction + TRACES regex fallback
│   ├── zerodha.py           Zerodha Tax P&L (XLSX/CSV/PDF)
│   ├── upstox.py            Upstox Realized P&L (XLSX)
│   ├── bank_statement.py    Bank statements (any Indian bank — bank-agnostic)
│   └── vision.py            Vision model OCR fallback
│
├── rag/                     Tax knowledge retrieval
│   ├── knowledge/           Markdown files: slabs, CG, deductions, VDA, ESOPs, tips
│   ├── indexer.py           Chunk + embed (BAAI/bge-small-en-v1.5, local CPU)
│   └── retriever.py         Top-k semantic search during conversation
│
└── output_builders/         Zero LLM
    ├── itr_json.py          map_to_itr1/2() + map_to_official_itr1/2() (IT Dept schema)
    ├── regime_report.py     Regime comparison JSON report
    └── pdf_summary.py       DRAFT PDF with watermark + 10-step portal filing guide
```

---

## ❌ What IndITR Doesn't Cover

| Scenario | Reason |
|---|---|
| **Upstox F&O P&L** | Only EQ sheet parsed; F&O not yet implemented |
| **Other brokers** (Groww, Angel One, Fyers) | No dedicated parser; vision fallback only |
| **Multiple employers in one FY** | Assumes single Form 16; Part A consolidation not implemented |
| **Brought-forward capital losses** | Only current-year gains; carry-forward not tracked |
| **Let-out property rental income** | HP loss offset implemented; positive rental income not extracted |
| **VDA/Crypto trade import** | Gains entered manually in gap-fill; no exchange CSV parser |
| **ESOPs/RSUs (auto-computation)** | Perquisite from Form 16 captured; sale CG computed normally |
| **Foreign assets / NRI filing** | ITR-2 Schedule FA not targeted |
| **Business / freelance income** | ITR-3; out of scope |
| **ITR-3, ITR-4** | Only ITR-1 and ITR-2 |
| **Income Tax Act 2025** | Applies from AY 2027-28; this tool targets AY 2026-27 under ITA 1961 |

---

## 🔒 Security & Privacy

- **PAN masking**: all PANs written as `XXXXX0000X` in every log, response, and output file — the raw PAN never leaves the engine
- **DRAFT watermark**: every page of generated PDFs has "DRAFT — Verify before filing"
- **Local by default**: state lives in your `sessions.db` SQLite file; no data sent anywhere except your chosen LLM endpoint
- **LLM sees text only**: raw extracted text is sent to the LLM; every output is validated by Pydantic before touching the engine
- **Crash-safe**: SqliteSaver checkpoints state after every node — mid-session restart resumes exactly where it left off

---

## 📄 License

[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — free for personal and educational use. Commercial use requires explicit permission from the author. Contact: [acervenky](https://github.com/acervenky).

---

<div align="center">

**Adequately Engineered with ☕ by Venky**

*Because sometimes, adequate is perfect.*

[Over Engineered by Venky →](https://github.com/acervenky/over-engineered-solar-pcu)

</div>