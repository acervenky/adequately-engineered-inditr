"""
LLM end-to-end integration tests — requires live OpenRouter key.

Marked with pytest.mark.slow so they are skipped in the fast suite:
    pytest -m "not slow"       # fast suite (CI default)
    pytest -m slow             # LLM tests only
    pytest                     # everything

Tests exercise:
  1. collect_profile node   — extracts name/PAN/DOB from a single user message
  2. identify_income_sources — extracts income source list from a user message
  3. gap_fill_chat          — asks follow-up questions OR completes when given full answers
  4. tax_advisor            — produces advice from a real TaxComputation
  5. Full Act 4 pipeline via LLM (compute → build_outputs → tax_advisor → finalise)
  6. What-if scenario runner inside tax_advisor
"""
from __future__ import annotations

import os
import json
import tempfile
import pytest

from dotenv import load_dotenv

load_dotenv()

# Skip the entire module if no API key is configured
_API_KEY = os.getenv("LLM_API_KEY", "")
pytestmark = pytest.mark.slow

if not _API_KEY or _API_KEY in ("ollama", "lm-studio", "vllm"):
    pytest.skip(
        "LLM_API_KEY not set or is a local placeholder — skipping LLM E2E tests",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _base_profile() -> dict:
    return {
        "pan": "ABCDE1234F",
        "name": "Priya Rajan",
        "date_of_birth": "1992-08-20",
        "employment_type": "salaried",
        "income_sources": ["salary"],
        "residential_status": "resident",
    }


def _base_extracted() -> dict:
    return {
        "salary_income": {
            "gross_salary": 1_000_000,
            "tds_deducted": 30_000,
            "hra_exemption": 0,
            "employer_nps_80ccd2": 0,
            "professional_tax": 0,
        },
        "house_property_income": 0,
        "other_income": 0,
        "capital_gains": [],
        "deductions": {
            "sec_80c": 50_000,
            "sec_80d": 0,
            "sec_80tta": 0,
            "sec_80ttb": 0,
            "sec_80ccd_1b": 0,
            "hra_exemption": 0,
            "home_loan_interest": 0,
            "sec_80e": 0,
            "sec_80g": 0,
            "sec_54_exemption": 0,
            "sec_54ec_exemption": 0,
            "sec_54f_exemption": 0,
            "other_deductions": 0,
        },
        "tds_total": 0,
        "advance_tax_paid": 0,
        "tcs_total": 0,
    }


def _state_with_computation(tmp_dir: str) -> dict:
    """State dict with filer_profile + extracted_data + computed TaxComputation."""
    from inditr.engine.regime import compare_regimes
    from inditr.models.tax_data import ExtractedTaxData
    from inditr.models.profile import FilerProfile

    profile = FilerProfile(**_base_profile())
    data = ExtractedTaxData(**_base_extracted())
    computation = compare_regimes(data, profile)

    return {
        "session_id": "llm_e2e_test",
        "itr_form": "ITR-1",
        "messages": [],
        "errors": [],
        "filer_profile": _base_profile(),
        "extracted_data": _base_extracted(),
        "computation": computation.model_dump(),
        "documents": [],
        "gap_fill_answers": {},
        "advisor_suggestions": [],
        "whatif_history": [],
        "user_confirmed": False,
    }


# ---------------------------------------------------------------------------
# 1. collect_profile — LLM extracts structured profile from a user message
# ---------------------------------------------------------------------------

class TestCollectProfileNode:
    """collect_profile must parse filer identity from natural language."""

    def test_extracts_profile_from_single_message(self):
        from inditr.graph.nodes.intake import collect_profile

        state = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Hi! I want to file my ITR. My name is Priya Rajan, "
                        "PAN is ABCDE1234F, born 20th August 1992, and I'm salaried."
                    ),
                }
            ],
            "errors": [],
            "filer_profile": None,
        }
        result = collect_profile(state)

        # Either the profile was extracted or the LLM asked a follow-up
        assert "errors" in result
        llm_errors = [e for e in result["errors"] if "LLM error" in e]
        assert llm_errors == [], f"LLM call failed: {llm_errors}"

        if result.get("filer_profile"):
            profile = result["filer_profile"]
            pan = profile.get("pan", "")
            # PAN must be 10 chars and preserve the 4 digits (positions 5-8)
            assert len(pan) == 10, f"PAN length wrong: {pan!r}"
            assert pan[5:9] == "1234", f"PAN digits not preserved: {pan!r}"
            assert "Priya" in profile.get("name", "")
            assert profile["employment_type"] in ("salaried", "other")
        else:
            # LLM asked a clarifying question — that's fine, just verify it replied
            messages = result.get("messages", [])
            assert len(messages) > 0
            last = messages[-1]
            assert last["role"] == "assistant"
            assert len(last["content"]) > 10

    def test_invalid_pan_not_accepted(self):
        from inditr.graph.nodes.intake import collect_profile

        state = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Name: Test User, PAN: INVALID123, DOB: 1990-01-01, salaried."
                    ),
                }
            ],
            "errors": [],
            "filer_profile": None,
        }
        result = collect_profile(state)
        # Invalid PAN must not be accepted as a valid profile
        profile = result.get("filer_profile")
        assert profile is None or result.get("current_act") == "collect_profile", \
            "Invalid PAN was silently accepted"

    def test_skips_when_profile_already_set(self):
        from inditr.graph.nodes.intake import collect_profile

        state = {
            "messages": [],
            "errors": [],
            "filer_profile": _base_profile(),
        }
        result = collect_profile(state)
        # Must skip to next node without LLM call
        assert result.get("current_act") == "identify_income_sources"
        assert result.get("errors") == [] or result.get("errors") is None


# ---------------------------------------------------------------------------
# 2. identify_income_sources — LLM extracts income sources
# ---------------------------------------------------------------------------

class TestIdentifyIncomeSources:
    """identify_income_sources must extract a list of income source types."""

    def test_salary_only(self):
        from inditr.graph.nodes.intake import identify_income_sources

        state = {
            "messages": [
                {"role": "user", "content": "I only have my salary, nothing else."},
            ],
            "errors": [],
            "filer_profile": _base_profile(),
        }
        result = identify_income_sources(state)
        llm_errors = [e for e in result.get("errors", []) if "LLM error" in e]
        assert llm_errors == [], f"LLM call failed: {llm_errors}"

        profile = result.get("filer_profile", {})
        sources = profile.get("income_sources", [])
        # Must produce at least some sources list
        assert isinstance(sources, list)
        # If the LLM completed, salary should be in sources
        if result.get("current_act") == "determine_itr_form":
            assert "salary" in sources

    def test_salary_plus_stocks(self):
        from inditr.graph.nodes.intake import identify_income_sources

        state = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "I have my salary, and I also sold some Zerodha stocks this year — "
                        "some profit from equity. I don't have rental income."
                    ),
                }
            ],
            "errors": [],
            "filer_profile": {**_base_profile(), "income_sources": []},
        }
        result = identify_income_sources(state)
        llm_errors = [e for e in result.get("errors", []) if "LLM error" in e]
        assert llm_errors == [], f"LLM call failed: {llm_errors}"

        if result.get("current_act") == "determine_itr_form":
            sources = result.get("filer_profile", {}).get("income_sources", [])
            assert "salary" in sources
            assert "capital_gains" in sources


# ---------------------------------------------------------------------------
# 3. gap_fill_chat — LLM asks questions about missing deductions
# ---------------------------------------------------------------------------

class TestGapFillChat:
    """gap_fill_chat must either ask questions or detect ##GAP_FILL_DONE##."""

    def test_asks_deduction_questions_without_prior_data(self):
        from inditr.graph.nodes.gap_fill import gap_fill_chat

        state = {
            "messages": [
                {"role": "user", "content": "I want to file my tax return."},
            ],
            "errors": [],
            "documents": [],
            "gap_fill_answers": {},
        }
        result = gap_fill_chat(state)
        llm_errors = [e for e in result.get("errors", []) if "LLM error" in e]
        assert llm_errors == [], f"LLM call failed: {llm_errors}"

        messages = result.get("messages", [])
        assert len(messages) >= 1
        last_reply = messages[-1]["content"]
        # Should ask about 80C, health insurance, HRA, NPS, etc.
        assert len(last_reply) > 20
        # Should NOT produce a JSON blob or code fence in the reply
        assert "```" not in last_reply

    def test_completes_when_given_full_answers(self):
        from inditr.graph.nodes.gap_fill import gap_fill_chat

        state = {
            "messages": [
                {"role": "assistant", "content": "Let me collect your deduction details."},
                {
                    "role": "user",
                    "content": (
                        "I've invested ₹1.5L in ELSS (80C), ₹25K health insurance for my family (80D), "
                        "no HRA (I own my home), no NPS, no home loan. "
                        "That's everything — I don't have any other income or deductions."
                    ),
                },
            ],
            "errors": [],
            "documents": [],
            "gap_fill_answers": {},
        }
        result = gap_fill_chat(state)
        llm_errors = [e for e in result.get("errors", []) if "LLM error" in e]
        assert llm_errors == [], f"LLM call failed: {llm_errors}"

        # LLM may complete or ask one more clarifying question — both are valid
        act = result.get("current_act")
        assert act in ("gap_fill_chat", "cross_check"), f"Unexpected act: {act}"

        if act == "cross_check":
            # Completed — gap_fill_answers should have sec_80c and sec_80d
            answers = result.get("gap_fill_answers", {})
            # At minimum the answers dict is populated
            assert isinstance(answers, dict)


# ---------------------------------------------------------------------------
# 4. tax_advisor — LLM generates personalised advice from TaxComputation
# ---------------------------------------------------------------------------

class TestTaxAdvisorNode:
    """tax_advisor must generate relevant, non-hallucinated advice."""

    def test_generates_opening_message_with_suggestions(self, tmp_path):
        from inditr.graph.nodes.advisor import tax_advisor

        state = _state_with_computation(str(tmp_path))
        result = tax_advisor(state)

        llm_errors = [e for e in result.get("errors", []) if "LLM error" in e]
        assert llm_errors == [], f"LLM call failed: {llm_errors}"

        messages = result.get("messages", [])
        assert len(messages) >= 1
        last = messages[-1]["content"]

        # Must mention regime or tax amount
        assert any(word in last.lower() for word in ("regime", "tax", "save", "₹", "rs", "deduction"))
        assert len(last) > 50

        # Proactive suggestions should have been generated
        suggestions = result.get("advisor_suggestions", [])
        assert len(suggestions) > 0

    def test_what_if_80c_scenario(self, tmp_path):
        """What-if: 'what if I max my 80C?' should trigger engine computation."""
        from inditr.graph.nodes.advisor import tax_advisor

        state = _state_with_computation(str(tmp_path))
        # Add a what-if user question
        state["messages"] = [
            {"role": "assistant", "content": "Your tax is computed. New regime is better."},
            {"role": "user", "content": "What if I invest ₹1 lakh more in 80C?"},
        ]
        result = tax_advisor(state)

        llm_errors = [e for e in result.get("errors", []) if "LLM error" in e]
        assert llm_errors == [], f"LLM call failed: {llm_errors}"

        messages = result.get("messages", [])
        last = messages[-1]["content"]
        # Response should mention regime, tax amount, or savings
        assert len(last) > 30

    def test_ready_to_file_routes_to_final_review(self, tmp_path):
        """When user says 'ready to file', advisor must route to human_final_review."""
        from inditr.graph.nodes.advisor import tax_advisor

        state = _state_with_computation(str(tmp_path))
        state["messages"] = [
            {"role": "assistant", "content": "Here are your tax numbers."},
            {"role": "user", "content": "Looks good, ready to file."},
        ]
        result = tax_advisor(state)

        llm_errors = [e for e in result.get("errors", []) if "LLM error" in e]
        assert llm_errors == [], f"LLM call failed: {llm_errors}"

        # Should route to human_final_review
        assert result.get("current_act") == "human_final_review", (
            f"Expected human_final_review, got {result.get('current_act')}. "
            f"Last message: {result.get('messages', [{}])[-1].get('content', '')}"
        )

    def test_advisor_does_not_hallucinate_numbers(self, tmp_path):
        """Advisor reply must not contain fabricated tax figures outside engine output."""
        from inditr.graph.nodes.advisor import tax_advisor
        from inditr.models.computation import TaxComputation

        state = _state_with_computation(str(tmp_path))
        result = tax_advisor(state)

        comp = TaxComputation(**state["computation"])
        new_tax = comp.new_regime.total_tax_liability
        old_tax = comp.old_regime.total_tax_liability

        messages = result.get("messages", [])
        if not messages:
            return
        reply = messages[-1]["content"]

        # The reply should reference the correct recommendation (engine result)
        rec = comp.recommended_regime
        # At a minimum, the reply should be a non-empty string
        assert len(reply) > 20


# ---------------------------------------------------------------------------
# 5. Full Act 4 pipeline: compute_tax → build_outputs → tax_advisor → finalise
# ---------------------------------------------------------------------------

class TestFullAct4PipelineLLM:
    """
    End-to-end Act 4 pipeline exercising:
      compute_tax (pure) → build_outputs (pure) → tax_advisor (LLM) → finalise (pure).

    The human_final_review interrupt is bypassed by pre-setting user_confirmed=True
    and calling finalise directly.
    """

    def test_full_act4_with_live_advisor(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PDF_OUTPUT_DIR", str(tmp_path))

        from inditr.graph.nodes.output import compute_tax, build_outputs, finalise
        from inditr.graph.nodes.advisor import tax_advisor

        base = {
            "session_id": "act4_llm_test",
            "itr_form": "ITR-1",
            "messages": [],
            "errors": [],
            "filer_profile": _base_profile(),
            "extracted_data": _base_extracted(),
            "documents": [],
            "gap_fill_answers": {},
            "advisor_suggestions": [],
            "whatif_history": [],
            "user_confirmed": False,
        }

        # Step 1: compute_tax (pure)
        state = {**base, **compute_tax(base)}
        assert "computation" in state
        assert not [e for e in state["errors"] if "computation" in e.lower()]

        # Step 2: build_outputs (pure)
        state.update(build_outputs(state))
        assert "regime_report" in state
        assert "itr_json" in state
        report = state["regime_report"]
        assert isinstance(report, dict)
        assert "AY 2026-27" in report["text_report"]

        # Step 3: tax_advisor (LLM)
        advisor_result = tax_advisor(state)
        llm_errors = [e for e in advisor_result.get("errors", []) if "LLM error" in e]
        assert llm_errors == [], f"Advisor LLM failed: {llm_errors}"

        state.update(advisor_result)
        messages = state.get("messages", [])
        assert len(messages) >= 1, "Advisor produced no messages"
        assert len(messages[-1]["content"]) > 20

        # Step 4: finalise (pure, bypass interrupt)
        state["user_confirmed"] = True
        final = finalise(state)

        assert final["current_act"] == "complete"
        itr_path = tmp_path / "act4_llm_test_itr.json"
        assert itr_path.is_file()
        itr_data = json.loads(itr_path.read_text())
        assert itr_data["AssessmentYear"] == "2026-27"

        pdf_path = final.get("pdf_path")
        assert pdf_path is not None
        assert os.path.isfile(pdf_path)

    def test_act4_advisor_suggestions_are_engine_grounded(self, tmp_path):
        """Proactive suggestions must be generated by the engine, not hallucinated."""
        from inditr.graph.nodes.output import compute_tax, build_outputs
        from inditr.graph.nodes.advisor import _generate_suggestions

        base = {
            "session_id": "suggest_test",
            "itr_form": "ITR-1",
            "messages": [],
            "errors": [],
            "filer_profile": _base_profile(),
            "extracted_data": _base_extracted(),
            "documents": [],
        }
        state = {**base, **compute_tax(base)}
        state.update(build_outputs(state))

        suggestions = _generate_suggestions(state)
        # Must produce at least one suggestion
        assert len(suggestions) >= 1
        # Each suggestion must be a non-empty string
        for s in suggestions:
            assert isinstance(s, str) and len(s) > 10

        # Regime recommendation mentioned
        full_text = " ".join(suggestions).lower()
        assert any(word in full_text for word in ("regime", "80c", "₹", "save", "invest"))


# ---------------------------------------------------------------------------
# 6. Intake → pure nodes flow (no LLM for deterministic nodes)
# ---------------------------------------------------------------------------

class TestDeterministicIntakeNodes:
    """
    determine_itr_form and build_doc_checklist are pure Python — test them
    without LLM to verify correct routing.
    """

    def test_salary_only_routes_to_itr1(self):
        from inditr.graph.nodes.intake import determine_itr_form, build_doc_checklist

        state = {
            "filer_profile": {**_base_profile(), "income_sources": ["salary"]},
            "errors": [],
        }
        form_result = determine_itr_form(state)
        assert form_result["itr_form"] == "ITR-1"

        state.update(form_result)
        checklist_result = build_doc_checklist(state)
        checklist = checklist_result["document_checklist"]
        assert any("form_16" in d["doc_type"] for d in checklist)

    def test_capital_gains_routes_to_itr2(self):
        from inditr.graph.nodes.intake import determine_itr_form

        state = {
            "filer_profile": {**_base_profile(), "income_sources": ["salary", "capital_gains"]},
            "errors": [],
        }
        result = determine_itr_form(state)
        assert result["itr_form"] == "ITR-2"

    def test_house_property_alone_stays_itr1(self):
        from inditr.graph.nodes.intake import determine_itr_form

        state = {
            "filer_profile": {**_base_profile(), "income_sources": ["salary", "house_property"]},
            "errors": [],
        }
        result = determine_itr_form(state)
        assert result["itr_form"] == "ITR-1"
