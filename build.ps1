# =============================================================================
# IndITR — Autonomous Build Script (Windows PowerShell)
# Usage: .\build.ps1
# Requires: Claude Code installed (npm install -g @anthropic-ai/claude-code)
#           PowerShell 5.1+ or PowerShell 7+
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Config ────────────────────────────────────────────────────────────────────
$MAX_TURNS   = 80
$LOG_DIR     = ".\build_logs"
$SESSION_FILE = ".build_session_id"

New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

# ── Helpers ───────────────────────────────────────────────────────────────────
function Info  { param($msg) Write-Host "[IndITR] $msg" -ForegroundColor Green }
function Warn  { param($msg) Write-Host "[WARN]   $msg" -ForegroundColor Yellow }
function Err   { param($msg) Write-Host "[ERROR]  $msg" -ForegroundColor Red; exit 1 }

# ── Preflight ─────────────────────────────────────────────────────────────────
if (-not (Get-Command "claude" -ErrorAction SilentlyContinue)) {
    Err "Claude Code not installed. Run: npm install -g @anthropic-ai/claude-code"
}
if (-not (Test-Path "CLAUDE.md")) {
    Err "CLAUDE.md not found in project root. Copy it here first."
}
if (-not (Test-Path ".env")) {
    Warn ".env not found — make sure DEEPINFRA_API_KEY is set in your environment."
}

# ── Helper: run a phase ───────────────────────────────────────────────────────
function Run-Phase {
    param(
        [int]    $PhaseNum,
        [string] $PhaseName,
        [string] $Prompt
    )

    $Log = "$LOG_DIR\phase$PhaseNum.log"

    Info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    Info "Starting Phase ${PhaseNum}: $PhaseName"
    Info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Build args array
    $ClaudeArgs = @(
        "--print", $Prompt,
        "--dangerously-skip-permissions",
        "--max-turns", $MAX_TURNS,
        "--output-format", "json"
    )

    # Attach --resume if we have a saved session and this isn't Phase 1
    if ($PhaseNum -gt 1 -and (Test-Path $SESSION_FILE)) {
        $SessionId = Get-Content $SESSION_FILE -Raw
        $SessionId = $SessionId.Trim()
        if ($SessionId) {
            $ClaudeArgs += "--resume"
            $ClaudeArgs += $SessionId
            Info "Resuming session: $SessionId"
        }
    }

    # Run claude, capture output, tee to log
    $Output = & claude @ClaudeArgs 2>&1 | Tee-Object -FilePath $Log

    # Extract session ID from JSON output lines
    $NewSession = $null
    foreach ($Line in $Output) {
        $Line = $Line.Trim()
        if (-not $Line) { continue }
        try {
            $Json = $Line | ConvertFrom-Json -ErrorAction SilentlyContinue
            if ($Json) {
                $sid = $Json.session_id ?? $Json.sessionId ?? $Json.id ?? $null
                if ($sid) {
                    $NewSession = $sid
                    break
                }
            }
        } catch { }
    }

    if ($NewSession) {
        $NewSession | Set-Content $SESSION_FILE
        Info "Session ID saved: $NewSession"
    }

    Info "Phase $PhaseNum complete. Log: $Log"
    Write-Host ""
}

# =============================================================================
# PHASE 1 — Pydantic Data Contracts
# =============================================================================
$Phase1Prompt = @'
You are building IndITR autonomously. Read CLAUDE.md in the project root for all rules and constraints.

PHASE 1 TASK: Build ALL Pydantic data contracts in models/.

Create these files completely:
1. models/__init__.py
2. models/profile.py — EmploymentType, IncomeSourceType, FilerProfile (with PAN regex validator: 5 alpha + 4 digit + 1 alpha uppercase), DocumentRequest
3. models/documents.py — ExtractedField (value, source_document, source_page, source_section, confidence 0.0-1.0, requires_review if confidence < 0.85, raw_text), ParsedDocument (doc_id uuid, doc_type, filename, pages, parsed_at, fields dict, parse_errors, overall_confidence = min of field confidences)
4. models/tax_data.py — SalaryIncome, CapitalGain (with gain_type STCG/LTCG, asset_type enum), Deductions (80C max 150000, 80D, 80TTA max 10000, hra_exemption, 80CCD_1B max 50000), ExtractedTaxData
5. models/computation.py — SlabBreakdown, RegimeResult, TaxComputation (old_regime, new_regime, recommended_regime, savings_from_recommendation, recommendation_reason)
6. models/outputs.py — FilingOutputs, Clarification, CrossCheckResult (check, passed, severity literal[pass/warning/critical], message)
7. models/state.py — TaxFilingState TypedDict (all fields per spec: session_id, assessment_year, messages, current_act, filer_profile, itr_form, document_checklist, documents, low_confidence_fields, gap_fill_answers, cross_check_results, extracted_data, computation, user_confirmed, itr_json, regime_report, pdf_path, pending_clarifications, errors)

Then:
- Create tests/test_models/ with test files for each model covering: (a) valid construction, (b) invalid construction raises ValidationError, (c) field validators reject out-of-range values (80C > 150000, confidence > 1.0, invalid PAN)
- Create pyproject.toml with all dependencies (langgraph>=0.2, pydantic>=2.7, litellm, pdfplumber>=0.11, pdf2image, reportlab>=4.0, fastapi>=0.111, uvicorn, jsonschema>=4.22, pytest, pytest-cov, python-dotenv)
- Create .env.example with:
  DEEPINFRA_API_KEY=your_deepinfra_key_here
  LITELLM_MODEL=deepinfra/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B
  LITELLM_VISION_MODEL=deepinfra/nvidia/NVIDIA-Nemotron-2-Nano-VL
  LITELLM_API_BASE=https://api.deepinfra.com/v1/openai
  SQLITE_DB_PATH=sessions.db
  PDF_OUTPUT_DIR=./outputs
- Run: pip install -e ".[dev]" then pytest tests/test_models/ -v
- ALL tests must pass before you finish.
- Commit with message: "feat: Phase 1 — Pydantic data contracts + tests"
- Output the word PHASE1_DONE on the last line when complete.
'@

Run-Phase -PhaseNum 1 -PhaseName "Pydantic Data Contracts" -Prompt $Phase1Prompt

# =============================================================================
# PHASE 2 — Tax Computation Engine
# =============================================================================
$Phase2Prompt = @'
Phase 1 is complete. Continue building IndITR. Read CLAUDE.md for all rules.

PHASE 2 TASK: Build the deterministic tax computation engine in engine/. ZERO LLM calls anywhere in this phase.

Create these files completely:

1. engine/__init__.py
2. engine/slabs.py — AY 2024-25 slab tables hardcoded as constants (no runtime fetching).
   Old regime: 0-2.5L=nil, 2.5L-5L=5%, 5L-10L=20%, >10L=30%
   New regime: 0-3L=nil, 3L-7L=5%, 7L-10L=10%, 10L-12L=15%, 12L-15L=20%, >15L=30%
   Functions: compute_tax_old_regime(taxable_income: int, age: int) -> tuple[int, list[SlabBreakdown]]
              compute_tax_new_regime(taxable_income: int) -> tuple[int, list[SlabBreakdown]]
              apply_surcharge(basic_tax, gross_income) -> int  # 10%>50L, 15%>1Cr, 25%>2Cr
              apply_cess(tax_after_surcharge) -> int  # 4% health+education cess
              apply_87a_rebate(basic_tax, taxable_income, regime) -> int  # old:<=5L, new:<=7L

3. engine/deductions.py — Pure Python, no LLM:
   compute_standard_deduction(regime) -> int  # 75000 new / 50000 old
   compute_hra_exemption(gross_salary, hra_received, rent_paid_monthly, is_metro) -> int
   validate_80c(declared) -> int  # cap at 150000
   validate_80d(self, parents, self_senior, parents_senior) -> int
   validate_80tta_ttb(interest, is_senior) -> int  # 80TTA=10K / 80TTB=50K
   compute_total_deductions(deductions: Deductions, filer: FilerProfile) -> int

4. engine/capital_gains.py — Pure Python:
   classify_gain(buy_date, sell_date, asset_type) -> Literal["STCG","LTCG"]
   compute_stcg_tax(stcg_total) -> int  # 20% flat (post Budget 2024)
   compute_ltcg_tax(ltcg_total) -> int  # 12.5% after 1,25,000 exemption (equity/equity MF only — NOT property)
   aggregate_gains(gains: list[CapitalGain]) -> dict  # {stcg_total, ltcg_total, stcg_tax, ltcg_tax}

5. engine/tds.py — TDS reconciliation:
   reconcile_tds(tds_sources: list[dict], total_tax_liability: int) -> dict

6. engine/regime.py — Orchestrator:
   compare_regimes(data: ExtractedTaxData, filer: FilerProfile) -> TaxComputation
   # Pure function: same inputs = same outputs. No LLM, no side effects.

Then:
- Write tests/test_engine/ with AT MINIMUM 10 known test cases.
  Each test must assert: taxable_income, basic_tax, surcharge, cess, total_tax, refund_or_payable
  Include edge cases: slab boundaries, 87A rebate edges, senior citizen (60+), LTCG with/without exemption, HRA metro vs non-metro
- Run: pytest tests/test_engine/ -v
- ALL tests must pass.
- Commit: "feat: Phase 2 — deterministic tax computation engine + 10 test cases"
- Output PHASE2_DONE on last line when complete.
'@

Run-Phase -PhaseNum 2 -PhaseName "Tax Computation Engine" -Prompt $Phase2Prompt

# =============================================================================
# PHASE 3 — Document Parsers
# =============================================================================
$Phase3Prompt = @'
Phases 1 and 2 are complete. Continue building IndITR. Read CLAUDE.md for all rules.

PHASE 3 TASK: Build all document parsers in parsers/.

Create these files completely:

1. parsers/__init__.py
2. parsers/base.py — BaseParser ABC with: can_parse(filepath: str) -> bool, parse(filepath: str) -> ParsedDocument. Parsers NEVER raise unhandled exceptions.

3. parsers/form16.py — Form16Parser(BaseParser):
   - Part A: pdfplumber table extraction for TAN, PAN, quarter-wise TDS table
   - Part B: keyword-based extraction for Gross Salary, Standard Deduction, Section 80C, net taxable salary
   - Confidence: exact keyword match=0.95, fuzzy match=0.75, not found=0.0 + parse_error
   - PAN validation: must match FilerProfile.pan — mismatch=parse_error, halt
   - Handle both CBDT-standardised and employer-custom Form 16 layouts

4. parsers/salary_slip.py — SalarySlipParser(BaseParser):
   - Extract: basic salary, HRA, other allowances, deductions, net pay, month/year

5. parsers/zerodha.py — ZerodhaPnlParser(BaseParser):
   - PDF: pdfplumber.extract_table() for Scrip|ISIN|Buy Date|Buy Value|Sell Date|Sell Value|STCG/LTCG
   - CSV: csv.DictReader with column name mapping
   - asset_type inferred from ISIN prefix: INE=equity, 0P=mutual fund
   - Summary cross-check: if mismatch >1% add warning

6. parsers/upstox.py — UpstoxParser(BaseParser):
   - Columns: Scrip Name, Purchase Date, Sale Date, Purchase Amount, Sale Amount, Short Term, Long Term
   - Fallback to vision.py if format unrecognised

7. parsers/bank_statement.py — BankStatementParser(BaseParser):
   - Extract salary credits, broker payouts (Zerodha/Upstox/Angel One/Groww/HDFC Securities), FD interest
   - Support HDFC, SBI, ICICI, Axis, Kotak formats via keyword heuristics
   - Unknown format -> vision.py fallback

8. parsers/vision.py — VisionParser:
   parse_with_vision(filepath, doc_type, extraction_schema: type[BaseModel]) -> ParsedDocument
   - Convert PDF pages to images (pdf2image), encode each page as base64 JPEG
   - Import VISION_MODEL from graph/llm.py (nvidia/NVIDIA-Nemotron-2-Nano-VL on DeepInfra)
   - Call litellm.completion with image messages in OpenAI format:
     {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
   - Prompt must request JSON only matching the extraction_schema fields
   - Validate JSON response via Pydantic, confidence = 0.80
   - If schema validation fails -> parse_errors, do not crash
   - Single DEEPINFRA_API_KEY — no Anthropic key needed

9. parsers/registry.py — ParserRegistry:
   get_parser(filepath) -> BaseParser — tries each parser.can_parse() in priority order:
   Form16 > Zerodha > Upstox > SalarySlip > BankStatement > Vision (fallback)

Then:
- Write tests/test_parsers/ — for each parser: (a) required fields extracted, (b) confidence scores reasonable, (c) parse_errors correct for missing fields, (d) password-protected PDF returns parse_error gracefully
- Create data/samples/README.md explaining anonymised test PDF process
- Run: pytest tests/test_parsers/ -v
- ALL tests must pass.
- Commit: "feat: Phase 3 — document parsers (Form16, Zerodha, Upstox, Bank, Vision)"
- Output PHASE3_DONE on last line when complete.
'@

Run-Phase -PhaseNum 3 -PhaseName "Document Parsers" -Prompt $Phase3Prompt

# =============================================================================
# PHASE 4 — LangGraph Agent Graph
# =============================================================================
$Phase4Prompt = @'
Phases 1, 2, and 3 are complete. Continue building IndITR. Read CLAUDE.md for all rules.

PHASE 4 TASK: Build the complete LangGraph agent graph in graph/.

Create these files completely:

1. graph/__init__.py
2. graph/llm.py — single shared LLM initialisation:
   import litellm, os
   from dotenv import load_dotenv
   load_dotenv()
   litellm.api_base = os.getenv("LITELLM_API_BASE", "https://api.deepinfra.com/v1/openai")
   litellm.api_key  = os.getenv("DEEPINFRA_API_KEY")
   MODEL        = os.getenv("LITELLM_MODEL",        "deepinfra/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B")
   VISION_MODEL = os.getenv("LITELLM_VISION_MODEL", "deepinfra/nvidia/NVIDIA-Nemotron-2-Nano-VL")
   All LLM nodes import MODEL from here. parsers/vision.py imports VISION_MODEL from here.
   Single DEEPINFRA_API_KEY covers both. Never hardcode model strings in individual files.

3. graph/checkpointer.py — SqliteSaver setup from SQLITE_DB_PATH env var

4. graph/nodes/__init__.py
5. graph/nodes/intake.py — Act 1 nodes:
   - collect_profile(state): LLM conversational intake, extract name/PAN/DOB/employment type. Does NOT proceed until FilerProfile fully populated and PAN validates.
   - identify_income_sources(state): LLM — ask about capital gains, rental income, other sources
   - determine_itr_form(state): PURE PYTHON — SALARY only=ITR-1; CAPITAL_GAINS or HOUSE_PROPERTY=ITR-2
   - build_doc_checklist(state): PURE PYTHON — build DocumentRequest list from itr_form + profile flags

6. graph/nodes/documents.py — Act 2 nodes:
   - request_documents(state): LLM presents checklist in friendly numbered format with fallback instructions
   - parse_documents(state): NO LLM — run each uploaded file through ParserRegistry, store in state.documents
   - validate_extractions(state): NO LLM — check overall_confidence, populate low_confidence_fields if any field < 0.85
   - human_doc_review(state): INTERRUPT — surface low-confidence fields as numbered questions

7. graph/nodes/gap_fill.py — Act 3 nodes:
   - gap_fill_chat(state): LLM asks targeted questions about missing deductions, HRA, additional investments
   - cross_check(state): NO LLM — salary cross-check (+-2% tolerance), capital gains directional check, populate cross_check_results
   - aggregate_data(state): NO LLM — merge ParsedDocuments + gap_fill_answers into ExtractedTaxData. gap_fill values get source_document="user_input", confidence=1.0

8. graph/nodes/output.py — Act 4 nodes:
   - compute_tax(state): NO LLM — calls engine/regime.py compare_regimes()
   - build_outputs(state): NO LLM — calls all three output builders
   - human_final_review(state): INTERRUPT — show computation summary, ask for confirmation
   - finalise(state): NO LLM — write output files, mark session complete

9. graph/edges.py — ALL conditional edge functions:
   - route_after_validation: if low_confidence_fields -> human_doc_review; else -> gap_fill_chat
   - route_after_cross_check: if critical failures -> gap_fill_chat; else -> aggregate_data
   - route_after_final_review: if user_confirmed -> finalise; else -> aggregate_data

10. graph/graph.py — Graph assembly:
    build_graph() -> CompiledGraph
    Entry point: collect_profile
    interrupt_before: [human_doc_review, human_final_review]
    SqliteSaver checkpointer, thread_id = session_id

Then:
- Write tests/test_graph/ — test each node in isolation with mock state, test edge routing, test interrupt nodes pause correctly
- Run: pytest tests/test_graph/ -v
- ALL tests must pass.
- Commit: "feat: Phase 4 — LangGraph agent graph with all 13 nodes and conditional edges"
- Output PHASE4_DONE on last line when complete.
'@

Run-Phase -PhaseNum 4 -PhaseName "LangGraph Agent Graph" -Prompt $Phase4Prompt

# =============================================================================
# PHASE 5 — Output Builders + FastAPI Layer
# =============================================================================
$Phase5Prompt = @'
Phases 1-4 are complete. Final phase. Continue building IndITR. Read CLAUDE.md for all rules.

PHASE 5 TASK: Build output builders and the FastAPI API layer.

Create these files completely:

1. output_builders/__init__.py
2. output_builders/itr_json.py — ZERO LLM:
   - map_to_itr1(data, computation) -> dict
   - map_to_itr2(data, computation) -> dict
   - validate_against_schema(itr_dict, schema_path) using jsonschema.validate()
   - Store placeholder schemas in data/itr_schemas/itr1_ay2024_25.json and itr2_ay2024_25.json
   - Every field traceable to ExtractedTaxData or TaxComputation — no hardcoded or LLM values

3. output_builders/regime_report.py — ZERO LLM. Build regime comparison JSON:
   {assessment_year, filer_pan (masked XXXXX0000X), old_regime: {gross_income, total_deductions, taxable_income, basic_tax, surcharge, cess, capital_gains_tax, total_tax, tds_paid, refund, effective_rate, slab_breakdown}, new_regime: {...}, recommendation, savings, reason}

4. output_builders/pdf_summary.py — ReportLab PDF:
   - Cover page: Name, PAN (masked XXXXX0000X), AY, ITR form, generation timestamp
   - Income summary table, deductions table, regime comparison (side-by-side, highlighted recommendation)
   - TDS reconciliation table, source trace appendix (every number with source_document/page/section/confidence)
   - Watermark on every page: "DRAFT — Verify before filing"
   - Required disclaimer text on cover page

5. api/__init__.py
6. api/schemas.py — Request/response Pydantic models for all endpoints
7. api/routes/__init__.py
8. api/routes/session.py:
   - POST /session/start — create session, init TaxFilingState, return session_id
   - GET /session/{id} — return current_act, pending_clarifications, documents uploaded
   - GET /session/{id}/outputs — returns itr_json, regime_report, pdf_summary after finalise
   - POST /session/{id}/confirm — triggers finalise node
9. api/routes/chat.py:
   - POST /session/{id}/message — resume graph from SQLite checkpoint (thread_id=session_id), return assistant message + state updates
10. api/routes/upload.py:
    - POST /session/{id}/upload — multipart/form-data, triggers parse_documents, returns ParsedDocument summary + low_confidence_fields
11. api/main.py — FastAPI app, CORS, include all routers, health check at GET /health

12. Update README.md with:
    - Project description and architecture diagram (ASCII)
    - Setup: python -m venv venv, venv\Scripts\activate (Windows), pip install -e ".[dev]", copy .env.example to .env and fill DEEPINFRA_API_KEY
    - Run: uvicorn api.main:app --reload
    - Required disclaimer text

Final steps:
- Run: pytest --cov=inditr --cov-report=term-missing -v (target >85% coverage on engine/ and parsers/)
- Run: python -c "from api.main import app; print('API imports OK')"
- Fix any import errors or failures before finishing.
- Commit: "feat: Phase 5 — output builders (ITR JSON, regime report, PDF) + FastAPI layer"
- Final commit: "chore: IndITR v1 complete — AY 2024-25 ITR-1+ITR-2 filing agent"
- Output BUILD_COMPLETE on last line when done.
'@

Run-Phase -PhaseNum 5 -PhaseName "Output Builders + FastAPI Layer" -Prompt $Phase5Prompt

# =============================================================================
# Done
# =============================================================================
Info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
Info "IndITR build complete. All 5 phases done."
Info "Logs in: $LOG_DIR"
Info "Start the API: uvicorn api.main:app --reload"
Info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
