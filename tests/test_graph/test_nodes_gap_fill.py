"""
Tests for Act 3 gap fill nodes — pure Python nodes only.
"""
import pytest
from inditr.graph.nodes.gap_fill import cross_check, aggregate_data


class TestCrossCheck:
    def test_no_documents_passes_with_skip_message(self):
        state = {"documents": [], "errors": []}
        result = cross_check(state)
        assert isinstance(result["cross_check_results"], list)
        assert len(result["cross_check_results"]) >= 1
        # Should have a pass result for the skipped check
        assert any(r["passed"] for r in result["cross_check_results"])

    def test_salary_match_within_tolerance(self):
        state = {
            "documents": [
                {
                    "doc_type": "form_16",
                    "fields": {
                        "gross_salary": {"confidence": 0.95, "value": 700000},
                    },
                },
                {
                    "doc_type": "bank_statement",
                    "fields": {
                        "salary_credits": {
                            "confidence": 0.90,
                            "value": [
                                {"amount": 350000, "line": "salary apr"},
                                {"amount": 355000, "line": "salary may"},
                            ],
                        }
                    },
                },
            ],
            "errors": [],
        }
        result = cross_check(state)
        salary_check = next(
            (r for r in result["cross_check_results"] if r["check"] == "salary_form16_vs_bank"),
            None,
        )
        assert salary_check is not None

    def test_salary_mismatch_critical(self):
        state = {
            "documents": [
                {
                    "doc_type": "form_16",
                    "fields": {
                        "gross_salary": {"confidence": 0.95, "value": 1000000},
                    },
                },
                {
                    "doc_type": "bank_statement",
                    "fields": {
                        "salary_credits": {
                            "confidence": 0.90,
                            "value": [{"amount": 500000, "line": "salary"}],
                        }
                    },
                },
            ],
            "errors": [],
        }
        result = cross_check(state)
        salary_check = next(
            r for r in result["cross_check_results"]
            if r["check"] == "salary_form16_vs_bank"
        )
        assert salary_check["severity"] in ("warning", "critical")
        assert not salary_check["passed"]

    def test_cross_check_results_have_required_keys(self):
        state = {"documents": [], "errors": []}
        result = cross_check(state)
        for r in result["cross_check_results"]:
            assert "check" in r
            assert "passed" in r
            assert "severity" in r
            assert "message" in r


class TestAggregateData:
    def test_basic_salary_aggregation(self):
        # Use the correct Form 16 parser field names: "tds_deducted" (Part B),
        # NOT the old "total_tds" which was never produced by the parser.
        state = {
            "documents": [
                {
                    "doc_type": "form_16",
                    "fields": {
                        "gross_salary": {"confidence": 0.95, "value": 700000},
                        "tds_deducted": {"confidence": 0.95, "value": 30000},
                    },
                }
            ],
            "gap_fill_answers": {},
            "errors": [],
        }
        result = aggregate_data(state)
        assert "extracted_data" in result
        ed = result["extracted_data"]
        assert ed["salary_income"]["gross_salary"] == 700000
        # Form 16 TDS belongs in salary_income.tds_deducted; regime.py adds it
        # to the total separately — it must NOT also populate tds_total (double-count).
        assert ed["salary_income"]["tds_deducted"] == 30000
        assert ed["tds_total"] == 0.0

    def test_gap_fill_overrides_document_values(self):
        state = {
            "documents": [],
            "gap_fill_answers": {"gross_salary": 800000, "sec_80c": 150000},
            "errors": [],
        }
        result = aggregate_data(state)
        ed = result["extracted_data"]
        assert ed["salary_income"]["gross_salary"] == 800000
        assert ed["deductions"]["sec_80c"] == 150000

    def test_empty_state_produces_empty_extracted_data(self):
        state = {"documents": [], "gap_fill_answers": {}, "errors": []}
        result = aggregate_data(state)
        assert "extracted_data" in result
        ed = result["extracted_data"]
        assert ed["salary_income"] is None
        assert ed["capital_gains"] == []

    def test_errors_preserved(self):
        state = {
            "documents": [],
            "gap_fill_answers": {},
            "errors": ["prior_error"],
        }
        result = aggregate_data(state)
        assert "prior_error" in result["errors"]

    def test_debt_mf_reclassified_from_equity_mf(self):
        """
        Parser may mis-classify a debt MF as equity_mf when scheme name was
        unavailable at parse time.  aggregate_data must reclassify to debt_mf
        using the scrip name and emit a warning.
        """
        state = {
            "documents": [
                {
                    "doc_type": "zerodha_pnl",
                    "fields": {
                        "capital_gains": {
                            "confidence": 0.95,
                            "value": [
                                {
                                    "gain_type": "STCG",
                                    "asset_type": "equity_mf",   # parser mis-classified
                                    "scrip": "HDFC Liquid Fund Direct Growth",
                                    "isin": "INF179K01YF0",
                                    "gain_amount": 50000.0,
                                    "sell_value": 550000.0,
                                    "buy_value": 500000.0,
                                    "buy_date": "2024-06-01",    # post-Apr-2023 → slab rate
                                    "sell_date": "2025-01-15",
                                    "is_speculation": False,
                                }
                            ],
                        }
                    },
                }
            ],
            "gap_fill_answers": {},
            "errors": [],
        }
        result = aggregate_data(state)
        ed = result["extracted_data"]
        cgs = ed["capital_gains"]
        assert len(cgs) == 1
        # Must be reclassified to debt_mf
        assert cgs[0]["asset_type"] == "debt_mf"
        # A warning must be emitted so the user is informed
        assert any("debt" in e.lower() for e in result["errors"])

    def test_equity_mf_not_misclassified_as_debt(self):
        """Equity MF scheme names must remain equity_mf after aggregate_data."""
        state = {
            "documents": [
                {
                    "doc_type": "zerodha_pnl",
                    "fields": {
                        "capital_gains": {
                            "confidence": 0.95,
                            "value": [
                                {
                                    "gain_type": "LTCG",
                                    "asset_type": "equity_mf",
                                    "scrip": "Mirae Asset Large Cap Fund Direct Growth",
                                    "isin": "INF769K01010",
                                    "gain_amount": 80000.0,
                                    "sell_value": 280000.0,
                                    "buy_value": 200000.0,
                                    "buy_date": "2022-01-10",
                                    "sell_date": "2025-03-01",
                                    "is_speculation": False,
                                }
                            ],
                        }
                    },
                }
            ],
            "gap_fill_answers": {},
            "errors": [],
        }
        result = aggregate_data(state)
        ed = result["extracted_data"]
        cgs = ed["capital_gains"]
        assert len(cgs) == 1
        assert cgs[0]["asset_type"] == "equity_mf"
        # No debt warning for a pure equity MF
        assert not any("debt mutual fund" in e.lower() for e in result["errors"])
