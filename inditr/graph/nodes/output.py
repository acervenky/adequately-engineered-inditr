"""
Act 4 — Output nodes.
compute_tax, build_outputs, finalise are pure Python (no LLM).
human_final_review uses LangGraph interrupt.
"""
from __future__ import annotations
import os
from typing import Any

from inditr.models.state import TaxFilingState


def compute_tax(state: TaxFilingState) -> dict[str, Any]:
    """
    NO LLM — calls engine/regime.py compare_regimes().
    Pure deterministic computation.
    """
    from inditr.engine.regime import compare_regimes
    from inditr.models.tax_data import ExtractedTaxData
    from inditr.models.profile import FilerProfile

    errors = list(state.get("errors", []))
    extracted_raw = state.get("extracted_data")
    profile_raw = state.get("filer_profile")

    if not extracted_raw or not profile_raw:
        errors.append("compute_tax: missing extracted_data or filer_profile")
        return {"errors": errors, "current_act": "build_outputs"}

    try:
        extracted = ExtractedTaxData(**extracted_raw)
        profile = FilerProfile(**profile_raw)
        computation = compare_regimes(extracted, profile)
        return {
            "computation": computation.model_dump(),
            "current_act": "build_outputs",
            "errors": errors,
        }
    except Exception as e:
        errors.append(f"Tax computation error: {e}")
        return {"errors": errors, "current_act": "build_outputs"}


def build_outputs(state: TaxFilingState) -> dict[str, Any]:
    """
    NO LLM — build ITR JSON, regime report, and PDF summary.
    """
    errors = list(state.get("errors", []))
    computation_raw = state.get("computation")
    profile_raw = state.get("filer_profile", {})

    if not computation_raw:
        errors.append("build_outputs: no computation available")
        return {"errors": errors, "current_act": "tax_advisor"}

    try:
        from inditr.models.computation import TaxComputation
        computation = TaxComputation(**computation_raw)

        # Build regime report (text summary)
        old = computation.old_regime
        new = computation.new_regime
        rec = computation.recommended_regime

        report_lines = [
            "=" * 60,
            "INDITR TAX COMPUTATION SUMMARY — AY 2026-27",
            "=" * 60,
            "",
            "OLD REGIME:",
            f"  Gross Income:       ₹{old.gross_income:>12,.0f}",
            f"  Total Deductions:   ₹{old.total_deductions:>12,.0f}",
            f"  Taxable Income:     ₹{old.taxable_income:>12,.0f}",
            f"  Income Tax:         ₹{old.income_tax:>12,.0f}",
            f"  87A Rebate:         ₹{old.rebate_87a:>12,.0f}",
            f"  Surcharge:          ₹{old.surcharge:>12,.0f}",
            f"  Cess (4%):          ₹{old.health_education_cess:>12,.0f}",
            f"  Total Liability:    ₹{old.total_tax_liability:>12,.0f}",
            f"  TDS/Advance Tax:    ₹{old.tds_tcs_advance_tax:>12,.0f}",
            f"  Net Payable/(Refund):₹{old.net_payable_refundable:>11,.0f}",
            "",
            "NEW REGIME:",
            f"  Gross Income:       ₹{new.gross_income:>12,.0f}",
            f"  Total Deductions:   ₹{new.total_deductions:>12,.0f}",
            f"  Taxable Income:     ₹{new.taxable_income:>12,.0f}",
            f"  Income Tax:         ₹{new.income_tax:>12,.0f}",
            f"  87A Rebate:         ₹{new.rebate_87a:>12,.0f}",
            f"  Surcharge:          ₹{new.surcharge:>12,.0f}",
            f"  Cess (4%):          ₹{new.health_education_cess:>12,.0f}",
            f"  Total Liability:    ₹{new.total_tax_liability:>12,.0f}",
            f"  TDS/Advance Tax:    ₹{new.tds_tcs_advance_tax:>12,.0f}",
            f"  Net Payable/(Refund):₹{new.net_payable_refundable:>11,.0f}",
            "",
            f"RECOMMENDATION: {rec.upper()} REGIME",
            f"  Savings: ₹{computation.savings_from_recommendation:,.0f}",
            f"  Reason: {computation.recommendation_reason}",
            "",
            "=" * 60,
            "DISCLAIMER: IndITR is an open-source tool for tax preparation",
            "assistance. It does not constitute professional tax advice.",
            "All computations must be verified before filing.",
            "When in doubt, consult a qualified Chartered Accountant.",
            "=" * 60,
        ]
        text_report = "\n".join(report_lines)
        # Structured dict — text_report for file output, typed keys for frontend sidebar
        regime_report = {
            "text_report": text_report,
            "old_tax": float(old.total_tax_liability),
            "new_tax": float(new.total_tax_liability),
            "old_net_payable": float(old.net_payable_refundable),
            "new_net_payable": float(new.net_payable_refundable),
            "recommendation": rec,
            "savings": float(computation.savings_from_recommendation),
            "reason": computation.recommendation_reason,
        }

        # Build full ITR JSON using the proper output builders (map_to_itr1 / map_to_itr2)
        itr_json: dict = {}
        extracted_raw = state.get("extracted_data")
        if extracted_raw and profile_raw:
            try:
                from inditr.models.tax_data import ExtractedTaxData
                from inditr.models.profile import FilerProfile
                from inditr.output_builders.itr_json import map_to_itr1, map_to_itr2
                data = ExtractedTaxData(**extracted_raw)
                profile = FilerProfile(**profile_raw)
                itr_form = state.get("itr_form", "ITR-1")
                if itr_form == "ITR-2":
                    itr_json = map_to_itr2(data, computation, profile)
                else:
                    itr_json = map_to_itr1(data, computation, profile)
            except Exception as e:
                errors.append(f"ITR JSON builder error: {e}")
                # Fall back to minimal JSON so the rest of the pipeline continues
                pan_raw = profile_raw.get("pan", "ABCDE1234F") if profile_raw else "ABCDE1234F"
                itr_json = {
                    "AssessmentYear": "2026-27",
                    "Form": state.get("itr_form", "ITR-1"),
                    "PersonalInfo": {"PAN": "XXXXX" + pan_raw[5:9] + "X"},
                    "RecommendedRegime": rec,
                    "TaxSummary": {
                        "OldRegime": {"TotalTax": float(old.total_tax_liability)},
                        "NewRegime": {"TotalTax": float(new.total_tax_liability)},
                    },
                }

    except Exception as e:
        errors.append(f"Output build error: {e}")
        regime_report = "Error building report"
        itr_json = {}

    return {
        "regime_report": regime_report,
        "itr_json": itr_json,
        "current_act": "tax_advisor",
        "errors": errors,
    }


def tax_advisor(state: TaxFilingState) -> dict[str, Any]:
    """
    DEPRECATED — use inditr.graph.nodes.advisor.tax_advisor instead.
    The graph (graph.py) and REST dispatcher (chat.py) both now use the full advisor node.
    This function is kept only to avoid import errors in old test fixtures.
    """
    from inditr.graph.llm import MODEL
    from inditr.graph.tools import run_tool_loop

    errors = list(state.get("errors", []))
    messages = list(state.get("messages", []))
    computation_raw = state.get("computation")
    extracted_raw = state.get("extracted_data")
    profile_raw = state.get("filer_profile", {})

    advice = ""
    if computation_raw:
        try:
            from inditr.models.computation import TaxComputation
            comp = TaxComputation(**computation_raw)
            old = comp.old_regime
            new = comp.new_regime
            rec = comp.recommended_regime

            # Build context for LLM — current numbers already computed by engine
            dob = profile_raw.get("date_of_birth", "1990-01-01")
            gross = 0.0
            current_80c = 0.0
            current_80d = 0.0
            current_nps = 0.0
            stcg = 0.0
            ltcg = 0.0
            if extracted_raw:
                sal = (extracted_raw.get("salary_income") or {})
                gross = float(sal.get("gross_salary") or 0)
                ded = (extracted_raw.get("deductions") or {})
                current_80c = float(ded.get("sec_80c") or 0)
                current_80d = float(ded.get("sec_80d") or 0)
                current_nps = float(ded.get("sec_80ccd_1b") or 0)
                for cg in (extracted_raw.get("capital_gains") or []):
                    if cg.get("gain_type") == "STCG":
                        stcg += float(cg.get("gain_amount") or 0)
                    elif cg.get("gain_type") == "LTCG":
                        ltcg += float(cg.get("gain_amount") or 0)

            context = (
                f"Filer data for AY 2026-27: gross salary ₹{gross:,.0f}, "
                f"current 80C ₹{current_80c:,.0f} (max 1,50,000), "
                f"current 80D ₹{current_80d:,.0f}, "
                f"current NPS 80CCD(1B) ₹{current_nps:,.0f} (max 50,000), "
                f"STCG ₹{stcg:,.0f}, LTCG ₹{ltcg:,.0f}. "
                f"Engine result: {rec} regime recommended. "
                f"Old regime tax ₹{old.total_tax_liability:,.0f}, "
                f"new regime tax ₹{new.total_tax_liability:,.0f}."
            )

            system_prompt = (
                "You are IndITR, an Indian tax advisor for AY 2026-27. "
                "Give 2-3 specific, actionable tax-saving tips this filer may have overlooked. "
                "For any savings amount you mention, you MUST call the deduction_impact or "
                "estimate_tax tool to get the real number — never guess or compute yourself. "
                "Focus on: 80C shortfall (max ₹1.5L), 80D health insurance, NPS 80CCD(1B) (₹50K extra). "
                "Be concise — 1-2 sentences per tip. No preamble, no JSON in your final reply."
            )

            advice, _ = run_tool_loop(
                model=MODEL,
                messages=[{"role": "user", "content": f"Filer data: {context}"}],
                system_prompt=system_prompt,
            )

            # Pass tool context so deduction_impact can be called with right params
            _ = {  # metadata for future tool calls — accessible via context
                "date_of_birth": dob,
                "gross_salary": gross,
                "current_80c": current_80c,
                "current_80d": current_80d,
                "current_nps": current_nps,
                "stcg_equity": stcg,
                "ltcg_equity": ltcg,
            }

        except Exception as e:
            errors.append(f"tax_advisor LLM error: {e}")
            advice = ""

    if advice:
        messages = messages + [{"role": "assistant", "content": advice}]

    return {
        "messages": messages,
        "current_act": "human_final_review",
        "errors": errors,
    }


def human_final_review(state: TaxFilingState) -> dict[str, Any]:
    """
    Final confirmation node — routes to finalise or back to aggregate_data.

    LangGraph pauses BEFORE this node via interrupt_before=["human_final_review"].
    The API reads the regime_report from state, shows it to the user, receives
    yes/no, and sets user_confirmed in state before resuming. When this node
    runs, the decision is already in state.
    """
    messages = list(state.get("messages", []))
    user_confirmed = state.get("user_confirmed")

    if user_confirmed:
        messages = messages + [{"role": "assistant", "content":
            "Great! Generating your final ITR JSON and PDF — please wait a moment."
        }]
        return {"messages": messages, "user_confirmed": True, "current_act": "finalise"}
    else:
        messages = messages + [{"role": "assistant", "content":
            "No problem — let's go back and adjust. What would you like to change?"
        }]
        return {"messages": messages, "user_confirmed": False, "current_act": "aggregate_data"}


def finalise(state: TaxFilingState) -> dict[str, Any]:
    """
    NO LLM — write output files, mark session complete.
    """
    import json
    from pathlib import Path

    errors = list(state.get("errors", []))
    session_id = state.get("session_id", "session")
    itr_json = state.get("itr_json", {})
    regime_report_raw = state.get("regime_report", "")
    # Support both old string format and new structured dict format
    if isinstance(regime_report_raw, dict):
        regime_report = regime_report_raw.get("text_report", "")
    else:
        regime_report = str(regime_report_raw)

    output_dir = Path(os.getenv("PDF_OUTPUT_DIR", "./outputs"))
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = None
    itr_json_path = None

    # Write ITR JSON
    try:
        itr_json_path = str(output_dir / f"{session_id}_itr.json")
        with open(itr_json_path, "w", encoding="utf-8") as f:
            json.dump(itr_json, f, indent=2, ensure_ascii=False)
    except Exception as e:
        errors.append(f"ITR JSON write error: {e}")

    # Write regime report
    try:
        report_path = str(output_dir / f"{session_id}_regime_report.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(regime_report)
    except Exception as e:
        errors.append(f"Regime report write error: {e}")

    # Attempt full PDF generation using the rich pdf_summary builder
    try:
        from inditr.output_builders.pdf_summary import build_pdf_summary
        from inditr.models.computation import TaxComputation
        from inditr.models.tax_data import ExtractedTaxData
        from inditr.models.profile import FilerProfile

        computation_raw = state.get("computation")
        extracted_raw = state.get("extracted_data")
        profile_raw = state.get("filer_profile", {})
        documents_raw = state.get("documents", [])

        if computation_raw and extracted_raw and profile_raw:
            computation = TaxComputation(**computation_raw)
            data = ExtractedTaxData(**extracted_raw)
            profile = FilerProfile(**profile_raw)

            from inditr.models.documents import ParsedDocument
            parsed_docs = []
            for d in documents_raw:
                try:
                    parsed_docs.append(ParsedDocument(**d))
                except Exception:
                    pass

            itr_form = state.get("itr_form", "ITR-1")
            pdf_out = str(output_dir / f"{session_id}_tax_summary.pdf")
            pdf_path = build_pdf_summary(
                computation=computation,
                data=data,
                profile=profile,
                output_path=pdf_out,
                documents=parsed_docs or None,
                itr_form=itr_form,
            )
        else:
            # Fallback to plain-text PDF when structured data unavailable
            pdf_path = _generate_pdf(output_dir, session_id, regime_report)
    except Exception as e:
        errors.append(f"PDF generation error (non-critical): {e}")
        try:
            pdf_path = _generate_pdf(output_dir, session_id, regime_report)
        except Exception:
            pass

    return {
        "pdf_path": pdf_path,
        "itr_json": itr_json,
        "current_act": "complete",
        "errors": errors,
    }


def _generate_pdf(output_dir, session_id: str, content: str) -> str:
    """Generate a PDF report with watermark. Returns path to PDF."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.colors import Color

    pdf_path = str(output_dir / f"{session_id}_tax_report.pdf")
    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4

    def _draw_watermark(canvas_obj):
        canvas_obj.saveState()
        canvas_obj.setFont("Helvetica-Bold", 40)
        canvas_obj.setFillColor(Color(0.85, 0.85, 0.85, alpha=0.5))
        canvas_obj.translate(width / 2, height / 2)
        canvas_obj.rotate(45)
        canvas_obj.drawCentredString(0, 0, "DRAFT — Verify before filing")
        canvas_obj.restoreState()

    _draw_watermark(c)

    # Content
    c.setFont("Helvetica", 10)
    y = height - 50
    for line in content.splitlines():
        if y < 50:
            c.showPage()
            _draw_watermark(c)
            c.setFont("Helvetica", 10)
            y = height - 50
        c.drawString(50, y, line[:100])
        y -= 14

    c.save()
    return pdf_path
