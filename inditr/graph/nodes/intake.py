"""
Act 1 — Intake nodes.
collect_profile and identify_income_sources use LLM for conversation.
determine_itr_form and build_doc_checklist are pure Python.
"""
from __future__ import annotations
import json
import re
from typing import Any

from inditr.models.state import TaxFilingState
from inditr.models.profile import FilerProfile, EmploymentType, IncomeSourceType, DocumentRequest

_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def _strip_json_blocks(text: str) -> str:
    """Remove markdown code fences and bare JSON objects from LLM text."""
    # Remove ```json ... ``` and ``` ... ``` blocks
    text = re.sub(r'```[a-z]*\s*\{.*?\}\s*```', '', text, flags=re.DOTALL)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    # Remove bare top-level JSON objects (starts with { ends with })
    text = re.sub(r'^\s*\{[^}]*\}\s*$', '', text, flags=re.DOTALL | re.MULTILINE)
    return text.strip()

_MANDATORY_DOCS = {
    "ITR-1": [
        DocumentRequest(doc_type="form_16", description="Form 16 from employer (Part A + Part B)", mandatory=True),
        DocumentRequest(doc_type="form_26as", description="Form 26AS (Tax Credit Statement)", mandatory=True),
        DocumentRequest(doc_type="ais", description="Annual Information Statement (AIS)", mandatory=False, reason="Recommended for cross-verification"),
    ],
    "ITR-2": [
        DocumentRequest(doc_type="form_16", description="Form 16 from employer (Part A + Part B)", mandatory=True),
        DocumentRequest(doc_type="form_26as", description="Form 26AS (Tax Credit Statement)", mandatory=True),
        DocumentRequest(doc_type="capital_gains_statement", description="Capital Gains Statement (broker P&L report)", mandatory=True),
        DocumentRequest(doc_type="ais", description="Annual Information Statement (AIS)", mandatory=False),
    ],
}


def collect_profile(state: TaxFilingState) -> dict[str, Any]:
    """
    LLM conversational node: collect filer profile.
    Uses structured extraction to populate FilerProfile.
    Loops until PAN validates and all required fields present.
    """
    import litellm
    from inditr.graph.llm import MODEL

    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))

    # If profile already complete, skip
    existing_profile = state.get("filer_profile")
    if existing_profile:
        try:
            FilerProfile(**existing_profile)
            return {"current_act": "identify_income_sources"}
        except Exception:
            pass

    # System prompt for profile collection
    system_prompt = (
        "You are IndITR, a friendly Indian tax filing and investment advisor for AY 2026-27. "
        "Your users are mostly young working adults who want to file smartly and save more tax. "
        "Be warm, casual, and encouraging — not bureaucratic. "
        "Collect: full name, PAN (format: 5 letters + 4 digits + 1 letter, e.g. ABCDE1234F), "
        "date of birth (DD/MM/YYYY), and employment type (salaried/self-employed/pensioner). "
        "Once you have all details, respond with ONLY a JSON object with keys: "
        "name, pan, date_of_birth (YYYY-MM-DD), employment_type (salaried/self_employed/pensioner/other). "
        "IMPORTANT: In the JSON output, include the EXACT PAN the user provided (e.g. ABCDE1234F) — do NOT mask it. "
        "In conversational replies (non-JSON), always mask the PAN as XXXXX####X for privacy."
    )

    # Build conversation
    llm_messages = [{"role": "system", "content": system_prompt}]
    llm_messages.extend(messages)

    if not messages:
        llm_messages.append({
            "role": "user",
            "content": "Hey! I want to file my ITR for AY 2026-27 and make sure I'm not overpaying tax."
        })

    try:
        response = litellm.completion(
            model=MODEL,
            messages=llm_messages,
            temperature=0.3,
            max_tokens=512,
        )
        reply = response.choices[0].message.content or ""

        # Try to extract JSON profile from response
        json_match = re.search(r'\{[^{}]+\}', reply, re.DOTALL)
        if json_match:
            try:
                profile_data = json.loads(json_match.group())
                # Normalise employment_type
                emp_map = {
                    "salaried": "salaried", "self_employed": "self_employed",
                    "pensioner": "pensioner", "other": "other",
                    "self-employed": "self_employed",
                }
                if "employment_type" in profile_data:
                    profile_data["employment_type"] = emp_map.get(
                        profile_data["employment_type"].lower(), "other"
                    )
                # Validate PAN
                pan = profile_data.get("pan", "").strip().upper()
                if not _PAN_RE.match(pan):
                    raise ValueError(f"Invalid PAN format: {pan}")
                profile_data["pan"] = pan

                profile = FilerProfile(**profile_data)
                # Keep the confirmation brief — identify_income_sources fires
                # immediately after and will be the message the user actually sees.
                new_messages = messages + [
                    {"role": "assistant", "content": (
                        f"Perfect, {profile.name.split()[0]}! PAN noted (masked for privacy). "
                        f"Now let's figure out which income sources apply to you this year."
                    )}
                ]
                return {
                    "filer_profile": profile.model_dump(),
                    "messages": new_messages,
                    "current_act": "identify_income_sources",
                    "errors": errors,
                }
            except Exception as e:
                errors.append(f"Profile extraction error: {e}")

        # No valid JSON yet — return LLM reply as next message (strip any code blocks)
        clean_reply = _strip_json_blocks(reply) or reply
        new_messages = messages + [{"role": "assistant", "content": clean_reply}]
        return {
            "messages": new_messages,
            "current_act": "collect_profile",
            "errors": errors,
        }

    except Exception as e:
        errors.append(f"LLM error in collect_profile: {e}")
        return {
            "messages": messages,
            "current_act": "collect_profile",
            "errors": errors,
        }


def identify_income_sources(state: TaxFilingState) -> dict[str, Any]:
    """
    LLM node: identify all income sources.
    Asks about capital gains, rental income, other sources.
    """
    import litellm
    from inditr.graph.llm import MODEL

    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))
    profile = state.get("filer_profile", {})

    system_prompt = (
        "You are IndITR, a friendly advisor. Ask the user which income sources apply to them for AY 2026-27. "
        "Keep it conversational — think of it as a quick checklist. "
        "Check for: (1) salary, (2) capital gains from stocks/mutual funds/property, "
        "(3) rental income or home loan interest, (4) interest/dividend/freelance income. "
        "Encourage them to mention investments — it helps optimise their tax. "
        "Once confirmed, respond with ONLY a JSON object with key 'income_sources' "
        "as a list of: salary, capital_gains, house_property, other_sources."
    )

    llm_messages = [{"role": "system", "content": system_prompt}] + messages

    try:
        response = litellm.completion(
            model=MODEL,
            messages=llm_messages,
            temperature=0.3,
            max_tokens=512,
        )
        reply = response.choices[0].message.content or ""

        json_match = re.search(r'\{[^{}]+\}', reply, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                sources = data.get("income_sources", ["salary"])
                valid_sources = [s for s in sources if s in [e.value for e in IncomeSourceType]]
                if not valid_sources:
                    valid_sources = ["salary"]

                if profile:
                    profile["income_sources"] = valid_sources

                # Build a friendly plain-English confirmation — never show raw JSON in chat
                _labels = {
                    "salary":        "salary income",
                    "capital_gains": "capital gains (stocks / mutual funds)",
                    "house_property":"house property income",
                    "other_sources": "other income (freelance / dividends / interest)",
                }
                readable = [_labels.get(s, s) for s in valid_sources]
                if len(readable) == 1:
                    summary = readable[0]
                elif len(readable) == 2:
                    summary = f"{readable[0]} and {readable[1]}"
                else:
                    summary = ", ".join(readable[:-1]) + f", and {readable[-1]}"

                confirmation = (
                    f"Got it! I've noted your income sources: {summary}. "
                    f"Let me now determine the right ITR form and prepare your document checklist."
                )
                new_messages = messages + [{"role": "assistant", "content": confirmation}]
                return {
                    "filer_profile": profile,
                    "messages": new_messages,
                    "current_act": "determine_itr_form",
                    "errors": errors,
                }
            except Exception as e:
                errors.append(f"Income source extraction error: {e}")

        clean_reply = _strip_json_blocks(reply) or reply
        new_messages = messages + [{"role": "assistant", "content": clean_reply}]
        return {
            "messages": new_messages,
            "current_act": "identify_income_sources",
            "errors": errors,
        }

    except Exception as e:
        errors.append(f"LLM error in identify_income_sources: {e}")
        # Default to salary only
        if profile:
            profile["income_sources"] = ["salary"]
        return {
            "filer_profile": profile,
            "messages": messages,
            "current_act": "determine_itr_form",
            "errors": errors,
        }


def determine_itr_form(state: TaxFilingState) -> dict[str, Any]:
    """
    PURE PYTHON — no LLM.
    AY 2026-27 rules:
    - ITR-1: salary + up to 2 house properties + other sources + 112A LTCG ≤ ₹1.25L
    - ITR-2: any capital_gains declared (conservative — STCG always needs ITR-2, and
      LTCG amount is unknown at intake stage) or business income
    - house_property alone no longer forces ITR-2 (AY 2026-27 ITR-1 expansion)
    """
    profile = state.get("filer_profile", {})
    income_sources = profile.get("income_sources", ["salary"])
    errors = list(state.get("errors", []))

    itr_form = "ITR-1"
    for source in income_sources:
        if source in ("capital_gains", "business"):
            itr_form = "ITR-2"
            break

    return {
        "itr_form": itr_form,
        "current_act": "build_doc_checklist",
        "errors": errors,
    }


def build_doc_checklist(state: TaxFilingState) -> dict[str, Any]:
    """
    PURE PYTHON — no LLM.
    Build DocumentRequest list from itr_form + profile flags.
    """
    itr_form = state.get("itr_form", "ITR-1")
    profile = state.get("filer_profile", {})
    errors = list(state.get("errors", []))

    base_docs = _MANDATORY_DOCS.get(itr_form, _MANDATORY_DOCS["ITR-1"])
    checklist = [doc.model_dump() for doc in base_docs]

    # Add house property docs if declared (applicable for both ITR-1 and ITR-2)
    income_sources = profile.get("income_sources", [])
    if "house_property" in income_sources:
        checklist.append(DocumentRequest(
            doc_type="home_loan_statement",
            description="Home loan interest certificate from bank (for Section 24b deduction)",
            mandatory=False,
            reason="Required if claiming home loan interest deduction",
        ).model_dump())

    # Add bank statement if salary income
    if "salary" in income_sources:
        checklist.append(DocumentRequest(
            doc_type="bank_statement",
            description="Bank statement (6 months) for salary credit cross-check",
            mandatory=False,
            reason="Used to verify salary credits ±2% tolerance",
        ).model_dump())

    # Add salary slips if available
    if "salary" in income_sources:
        checklist.append(DocumentRequest(
            doc_type="salary_slip",
            description="Latest 3 salary slips (for HRA calculation)",
            mandatory=False,
            reason="Required if claiming HRA exemption",
        ).model_dump())

    return {
        "document_checklist": checklist,
        "current_act": "request_documents",
        "errors": errors,
    }
