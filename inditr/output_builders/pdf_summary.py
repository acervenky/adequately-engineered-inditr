"""
PDF summary builder using ReportLab.
Every page has watermark: "DRAFT — Verify before filing"
PAN masked XXXXX####X on all pages.
Required disclaimer on cover page.
ZERO LLM.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)
from reportlab.lib.colors import Color, HexColor

from inditr.models.computation import TaxComputation
from inditr.models.tax_data import ExtractedTaxData
from inditr.models.profile import FilerProfile
from inditr.models.documents import ParsedDocument

_DISCLAIMER = (
    "IndITR is an open-source tool for tax preparation assistance. "
    "It does not constitute professional tax advice. All computations must be "
    "verified by the user before filing. The authors assume no liability for "
    "errors, omissions, or penalties arising from use of this tool. "
    "When in doubt, consult a qualified Chartered Accountant."
)

_WATERMARK_TEXT = "DRAFT — Verify before filing"
_GREY = Color(0.75, 0.75, 0.75, alpha=0.4)
_HIGHLIGHT = HexColor("#E8F5E9")  # light green for recommended regime
_HEADER_BG = HexColor("#1565C0")  # dark blue
_HEADER_FG = colors.white


def _mask_pan(pan: str) -> str:
    if len(pan) == 10:
        return f"XXXXX{pan[5:9]}X"
    return "XXXXXXXXXX"


def _watermark_canvas(canvas, doc):
    """Draw watermark on every page."""
    canvas.saveState()
    width, height = A4
    canvas.setFont("Helvetica-Bold", 36)
    canvas.setFillColor(_GREY)
    canvas.translate(width / 2, height / 2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, _WATERMARK_TEXT)
    canvas.restoreState()
    # Page number
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawRightString(width - 20, 15, f"Page {doc.page}")
    canvas.restoreState()


def _fmt_inr(value: float) -> str:
    """Format as Indian Rupee with comma separator."""
    if value < 0:
        return f"(Rs.{abs(value):,.0f})"
    return f"Rs.{value:,.0f}"


def _table_style(header_rows: int = 1) -> TableStyle:
    cmds = [
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), _HEADER_FG),
        ("FONTNAME", (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ROWBACKGROUNDS", (0, header_rows), (-1, -1), [colors.white, HexColor("#F5F5F5")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    return TableStyle(cmds)


def build_pdf_summary(
    computation: TaxComputation,
    data: ExtractedTaxData,
    profile: FilerProfile,
    output_path: str,
    documents: list[ParsedDocument] | None = None,
    itr_form: str = "ITR-1",
) -> str:
    """
    Build a PDF tax summary report.
    Returns path to the generated PDF.
    Watermark on every page. PAN masked. Disclaimer on cover.
    ZERO LLM.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=20 * mm,
        title="IndITR Tax Summary -- AY 2026-27",
        author="IndITR",
    )

    styles = getSampleStyleSheet()
    h1 = styles["h1"]
    h2 = styles["h2"]
    normal = styles["Normal"]
    small = ParagraphStyle("small", parent=normal, fontSize=8, textColor=colors.grey)
    disclaimer_style = ParagraphStyle(
        "disclaimer", parent=normal, fontSize=8,
        textColor=colors.darkgrey, borderColor=colors.orange,
        borderWidth=1, borderPadding=6, backColor=HexColor("#FFF8E1"),
    )

    story = []

    # --- Cover Page ---
    story.append(Spacer(1, 20 * mm))
    story.append(Paragraph("IndITR -- Tax Filing Summary", h1))
    story.append(Paragraph("Assessment Year 2026-27", h2))
    story.append(Spacer(1, 8 * mm))

    emp_type = profile.employment_type
    emp_type_str = emp_type.value if hasattr(emp_type, "value") else str(emp_type)

    cover_data = [
        ["Field", "Value"],
        ["Filer Name", profile.name],
        ["PAN", _mask_pan(profile.pan)],
        ["Date of Birth", profile.date_of_birth],
        ["ITR Form", itr_form],
        ["Employment Type", emp_type_str],
        ["Recommended Regime", computation.recommended_regime.upper()],
        ["Generated At", datetime.now().strftime("%d %b %Y %H:%M")],
    ]
    t = Table(cover_data, colWidths=[70 * mm, 100 * mm])
    t.setStyle(_table_style(1))
    story.append(t)

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(_DISCLAIMER, disclaimer_style))
    story.append(PageBreak())

    # --- Income Summary ---
    story.append(Paragraph("Income Summary", h2))
    story.append(Spacer(1, 4 * mm))

    old = computation.old_regime
    new = computation.new_regime
    rec = computation.recommended_regime
    gross_salary = float(data.salary_income.gross_salary) if data.salary_income else 0.0

    income_data = [
        ["Income Head", "Amount"],
        ["Gross Salary", _fmt_inr(gross_salary)],
        ["House Property Income", _fmt_inr(float(data.house_property_income))],
        ["Other Income", _fmt_inr(float(data.other_income))],
    ]
    if data.capital_gains:
        from inditr.models.tax_data import GainType
        stcg = sum(g.gain_amount for g in data.capital_gains if g.gain_type == GainType.STCG)
        ltcg = sum(g.gain_amount for g in data.capital_gains if g.gain_type == GainType.LTCG)
        income_data.append(["Total STCG", _fmt_inr(float(stcg))])
        income_data.append(["Total LTCG", _fmt_inr(float(ltcg))])

    t = Table(income_data, colWidths=[100 * mm, 70 * mm])
    t.setStyle(_table_style(1))
    story.append(t)
    story.append(Spacer(1, 6 * mm))

    # --- Deductions Table ---
    story.append(Paragraph("Deductions", h2))
    story.append(Spacer(1, 4 * mm))
    d = data.deductions
    ded_data = [
        ["Deduction", "Amount", "Max Limit"],
        ["Standard Deduction (Sec 16)", _fmt_inr(50_000), _fmt_inr(50_000)],
        ["Section 80C", _fmt_inr(float(d.sec_80c)), "Rs.1,50,000"],
        ["Section 80D", _fmt_inr(float(d.sec_80d)), "Rs.25,000/Rs.50,000"],
        ["Section 80TTA", _fmt_inr(float(d.sec_80tta)), "Rs.10,000"],
        ["Section 80CCD(1B)", _fmt_inr(float(d.sec_80ccd_1b)), "Rs.50,000"],
        ["HRA Exemption", _fmt_inr(float(d.hra_exemption)), "Calculated"],
        ["Total Deductions (Old)", _fmt_inr(float(old.total_deductions)), "--"],
    ]
    t = Table(ded_data, colWidths=[80 * mm, 60 * mm, 30 * mm])
    t.setStyle(_table_style(1))
    story.append(t)
    story.append(Spacer(1, 6 * mm))

    # --- Regime Comparison (side-by-side) ---
    story.append(Paragraph("Regime Comparison", h2))
    story.append(Spacer(1, 4 * mm))

    old_col = "OLD REGIME (Recommended)" if rec == "old" else "OLD REGIME"
    new_col = "NEW REGIME (Recommended)" if rec == "new" else "NEW REGIME"

    old_gross = float(old.gross_income)
    new_gross = float(new.gross_income)

    comp_data = [
        ["Parameter", old_col, new_col],
        ["Gross Income", _fmt_inr(old_gross), _fmt_inr(new_gross)],
        ["Total Deductions", _fmt_inr(float(old.total_deductions)), _fmt_inr(float(new.total_deductions))],
        ["Taxable Income", _fmt_inr(float(old.taxable_income)), _fmt_inr(float(new.taxable_income))],
        ["Income Tax", _fmt_inr(float(old.income_tax)), _fmt_inr(float(new.income_tax))],
        ["87A Rebate", _fmt_inr(float(old.rebate_87a)), _fmt_inr(float(new.rebate_87a))],
        ["Surcharge", _fmt_inr(float(old.surcharge)), _fmt_inr(float(new.surcharge))],
        ["Cess (4%)", _fmt_inr(float(old.health_education_cess)), _fmt_inr(float(new.health_education_cess))],
        ["Total Tax Liability", _fmt_inr(float(old.total_tax_liability)), _fmt_inr(float(new.total_tax_liability))],
        ["TDS Paid", _fmt_inr(float(old.tds_tcs_advance_tax)), _fmt_inr(float(new.tds_tcs_advance_tax))],
        ["Net Payable/(Refund)", _fmt_inr(float(old.net_payable_refundable)), _fmt_inr(float(new.net_payable_refundable))],
        [
            "Effective Rate",
            f"{round(old.total_tax_liability / old_gross * 100, 1) if old_gross > 0 else 0}%",
            f"{round(new.total_tax_liability / new_gross * 100, 1) if new_gross > 0 else 0}%",
        ],
    ]

    t = Table(comp_data, colWidths=[70 * mm, 55 * mm, 55 * mm])
    ts = _table_style(1)
    # Highlight recommended column
    if rec == "old":
        ts.add("BACKGROUND", (1, 1), (1, -1), _HIGHLIGHT)
        ts.add("FONTNAME", (1, 0), (1, 0), "Helvetica-Bold")
    else:
        ts.add("BACKGROUND", (2, 1), (2, -1), _HIGHLIGHT)
        ts.add("FONTNAME", (2, 0), (2, 0), "Helvetica-Bold")
    # Highlight total row (index 8 = Total Tax Liability)
    ts.add("FONTNAME", (0, 8), (-1, 8), "Helvetica-Bold")
    t.setStyle(ts)
    story.append(t)

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        f"<b>Recommendation:</b> {rec.upper()} REGIME -- "
        f"Saves {_fmt_inr(float(computation.savings_from_recommendation))}. "
        f"{computation.recommendation_reason}",
        normal
    ))
    story.append(PageBreak())

    # --- TDS Reconciliation ---
    story.append(Paragraph("TDS Reconciliation", h2))
    story.append(Spacer(1, 4 * mm))

    r_rec = new if rec == "new" else old
    tds_data = [
        ["Item", "Amount"],
        ["Total Tax Liability", _fmt_inr(float(r_rec.total_tax_liability))],
        ["TDS Deducted (Employer)", _fmt_inr(float(r_rec.tds_tcs_advance_tax))],
        ["Net Payable / (Refund)", _fmt_inr(float(r_rec.net_payable_refundable))],
    ]
    t = Table(tds_data, colWidths=[100 * mm, 70 * mm])
    ts = _table_style(1)
    ts.add("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 6 * mm))

    # --- Source Trace Appendix ---
    if documents:
        story.append(Paragraph("Source Trace Appendix", h2))
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(
            "Every extracted value listed with source document, page, section, and confidence score.",
            small,
        ))
        story.append(Spacer(1, 4 * mm))

        trace_data = [["Field", "Value", "Source Doc", "Page", "Section", "Confidence"]]
        for parsed_doc in documents:
            for field_name, field in parsed_doc.fields.items():
                val = str(field.value)[:30] if field.value is not None else "--"
                trace_data.append([
                    field_name,
                    val,
                    Path(field.source_document).name[:25],
                    str(field.source_page or "--"),
                    str(field.source_section or "--")[:20],
                    f"{field.confidence:.0%}",
                ])

        if len(trace_data) > 1:
            col_widths = [40 * mm, 30 * mm, 40 * mm, 12 * mm, 30 * mm, 18 * mm]
            t = Table(trace_data, colWidths=col_widths, repeatRows=1)
            t.setStyle(_table_style(1))
            story.append(t)


    # --- Portal Filing Walkthrough ---
    story.append(PageBreak())
    story.append(Paragraph("How to File on the Income Tax Portal", h2))
    story.append(Spacer(1, 3 * mm))

    rec_regime = computation.recommended_regime
    r_rec = computation.new_regime if rec_regime == "new" else computation.old_regime
    net_payable = float(r_rec.net_payable_refundable)
    is_refund = net_payable < 0

    portal_intro_style = ParagraphStyle("portal_intro", parent=normal, fontSize=9, textColor=colors.darkgrey)
    step_head_style = ParagraphStyle("step_head", parent=normal, fontSize=10, fontName="Helvetica-Bold",
        textColor=_HEADER_BG, spaceAfter=2)
    step_body_style = ParagraphStyle("step_body", parent=normal, fontSize=9, leftIndent=12)
    value_style = ParagraphStyle("value_style", parent=normal, fontSize=9, leftIndent=24,
        fontName="Helvetica-Bold", textColor=HexColor("#1B5E20"))
    skipped_style = ParagraphStyle("skipped_step", parent=normal, fontSize=9,
        leftIndent=12, textColor=colors.grey)

    story.append(Paragraph(
        "Use the values below to fill the IT portal: https://www.incometaxindia.gov.in",
        portal_intro_style,
    ))
    story.append(Spacer(1, 4 * mm))

    gross_salary_val = float(data.salary_income.gross_salary) if data.salary_income else 0.0
    std_ded_val = 75_000 if rec_regime == "new" else 50_000
    employer_nps_val = float(data.salary_income.employer_nps_80ccd2) if data.salary_income else 0.0
    d = data.deductions

    steps = [
        ("Step 1 — Log in", [
            "Go to https://www.incometaxindia.gov.in",
            f"Log in with PAN ({_mask_pan(profile.pan)}) and password.",
            "Complete Aadhaar OTP or net-banking authentication if prompted.",
        ]),
        ("Step 2 — Start filing", [
            "Click: e-File > Income Tax Returns > File Income Tax Return",
            "Assessment Year: 2026-27",
            "Mode of Filing: Online  |  Status: Individual",
            f"ITR Form: {itr_form}  |  Filing Type: Original Return",
        ]),
        ("Step 3 — Verify pre-filled data", [
            "Portal pre-fills salary from Form 16 / AIS / 26AS.",
            "Cross-check gross salary against this report; correct any discrepancies.",
            "Verify TDS details under Schedule TDS-1.",
        ]),
        ("Step 4 — Choose tax regime", [
            f"Select: {rec_regime.upper()} REGIME (IndITR recommendation)",
            f"Saves: {_fmt_inr(float(computation.savings_from_recommendation))} vs the other regime",
        ]),
        ("Step 5 — Enter income details", [
            f"Gross Salary (Schedule S): {_fmt_inr(gross_salary_val)}",
            f"Standard Deduction (Sec 16): {_fmt_inr(std_ded_val)}",
            f"House Property Income: {_fmt_inr(float(data.house_property_income))}",
            f"Other Income: {_fmt_inr(float(data.other_income))}",
        ]),
        ("Step 6 — Enter deductions" + (" (old regime only — skip if new regime)" if rec_regime == "new" else ""), [
            f"80C: {_fmt_inr(float(d.sec_80c))}",
            f"80D: {_fmt_inr(float(d.sec_80d))}",
            f"80TTA: {_fmt_inr(float(d.sec_80tta))}",
            f"80CCD(1B): {_fmt_inr(float(d.sec_80ccd_1b))}",
            f"80CCD(2) Employer NPS: {_fmt_inr(employer_nps_val)} (both regimes)",
            f"HRA Exemption: {_fmt_inr(float(d.hra_exemption))}",
        ]),
        ("Step 7 — Verify tax computation", [
            f"Total Taxable Income: {_fmt_inr(float(r_rec.taxable_income))}",
            f"Total Tax Liability: {_fmt_inr(float(r_rec.total_tax_liability))}",
            f"TDS Already Paid: {_fmt_inr(float(r_rec.tds_tcs_advance_tax))}",
            (f"REFUND DUE: {_fmt_inr(abs(net_payable))}" if is_refund else f"TAX PAYABLE: {_fmt_inr(net_payable)}"),
        ]),
        ("Step 8 — Pay tax if due (skip if refund)", [] if is_refund else [
            f"Pay {_fmt_inr(net_payable)} via Challan 280 (click 'Pay Now').",
            "Select: (0021) Income Tax Other Than Companies",
            "Payment type: (300) Self Assessment Tax",
            "Enter Challan BSR Code, date, and serial number after payment.",
        ]),
        ("Step 9 — Preview and submit", [
            "Click 'Preview Return' and review all schedules.",
            "Accept the declaration and click 'Submit'.",
        ]),
        ("Step 10 — E-verify (mandatory within 30 days)", [
            "Preferred: e-Verify via Aadhaar OTP (instant).",
            "Alternate: Net banking, Demat account, bank account, or DSC.",
            "Or send signed ITR-V to CPC Bengaluru by speed post.",
            "Return is NOT processed until e-verification is complete.",
        ]),
    ]

    for step_title, bullets in steps:
        is_ded_step = "old regime only" in step_title
        is_pay_step = "pay tax if due" in step_title.lower()
        if rec_regime == "new" and is_ded_step:
            story.append(Paragraph(
                f"{step_title} — Skipped (New Regime; Chapter VI-A deductions not applicable)",
                skipped_style,
            ))
            story.append(Spacer(1, 2 * mm))
            continue
        if is_refund and is_pay_step:
            story.append(Paragraph(
                f"{step_title} — Skipped (refund of {_fmt_inr(abs(net_payable))} due to you)",
                skipped_style,
            ))
            story.append(Spacer(1, 2 * mm))
            continue
        story.append(Paragraph(step_title, step_head_style))
        for bullet in bullets:
            if ":" in bullet and any(kw in bullet for kw in ["Rs.", "REFUND", "TAX PAYABLE", "REGIME", "Saves"]):
                label, _, amount = bullet.partition(":")
                story.append(Paragraph(f"  {label}:", step_body_style))
                story.append(Paragraph(f"      {amount.strip()}", value_style))
            else:
                story.append(Paragraph(f"  •  {bullet}", step_body_style))
        story.append(Spacer(1, 3 * mm))

    offline_note_style = ParagraphStyle("offline_note", parent=normal, fontSize=8,
        textColor=colors.darkgrey, backColor=HexColor("#E3F2FD"),
        borderColor=HexColor("#1565C0"), borderWidth=1, borderPadding=5)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "<b>Alternative — Offline Utility:</b> Download the AY 2026-27 offline utility from "
        "incometaxindia.gov.in > Downloads > Offline Utilities. Use the "
        "/download/itr-json-official API endpoint to get the IT-Dept conformant JSON, "
        "import into the utility, verify all schedules, then upload on the portal.",
        offline_note_style,
    ))

    # --- Final disclaimer ---
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(_DISCLAIMER, disclaimer_style))

    doc.build(story, onFirstPage=_watermark_canvas, onLaterPages=_watermark_canvas)
    return output_path
