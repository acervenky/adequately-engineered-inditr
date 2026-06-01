"""
Parser registry — routes documents to the correct parser.

Routing strategy (two-stage):

  Stage 1 — LLM classifier (one call per file):
      filename + first ~3000 chars of content → doc_type string
      If confidence >= 0.70 → route directly to the mapped parser
      This handles all format variations without per-parser regex sniffers.

  Stage 2 — Legacy can_parse() chain (fallback):
      If LLM confidence < 0.70 or LLM call fails → try each parser's
      can_parse() in priority order (existing behaviour).
      Ensures nothing breaks if the LLM is unavailable.

  Final fallback — VisionFallbackParser:
      If no parser claims the file → vision OCR with generic schema.

Adding a new document type:
  1. Add the doc_type string to classifier._KNOWN_TYPES and _TYPE_DESCRIPTIONS
  2. Add the parser class to _TYPE_TO_PARSER below
  3. That's it — no new can_parse() logic needed
"""
from __future__ import annotations
import logging
import traceback

from inditr.models.documents import ParsedDocument
from .form16 import Form16Parser
from .zerodha import ZerodhaPnlParser
from .upstox import UpstoxParser
from .salary_slip import SalarySlipParser
from .bank_statement import BankStatementParser
from .base import BaseParser
from .classifier import classify_document, _MIN_CONFIDENCE

logger = logging.getLogger(__name__)

# doc_type → parser class (must match classifier._KNOWN_TYPES)
_TYPE_TO_PARSER: dict[str, type[BaseParser]] = {
    "zerodha_tax_pnl":     ZerodhaPnlParser,
    "upstox_realized_pnl": UpstoxParser,
    "form_16":             Form16Parser,
    "salary_slip":         SalarySlipParser,
    "bank_statement":      BankStatementParser,
    # form_26as, cams_mf_statement, nps_statement, home_loan_certificate
    # → not yet implemented, fall through to vision fallback
}

# Legacy priority order for the can_parse() fallback chain
_LEGACY_PARSERS: list[BaseParser] = [
    Form16Parser(),
    ZerodhaPnlParser(),
    UpstoxParser(),
    SalarySlipParser(),
    BankStatementParser(),
]


class ParserRegistry:
    """Routes files to the correct parser via LLM classification."""

    def get_parser(self, filepath: str) -> BaseParser:
        """
        Return the best parser for this file.
        Tries LLM classification first; falls back to legacy can_parse() chain.
        """
        # ── Stage 1: LLM classifier ───────────────────────────────────────────
        try:
            result = classify_document(filepath)
            logger.info(
                "Classifier: %s → %s (conf=%.2f) — %s",
                filepath, result.doc_type, result.confidence, result.reason,
            )

            if result.confidence >= _MIN_CONFIDENCE and result.doc_type in _TYPE_TO_PARSER:
                return _TYPE_TO_PARSER[result.doc_type]()

            if result.confidence >= _MIN_CONFIDENCE and result.doc_type != "unknown":
                # Identified but no parser yet → vision fallback with the known type
                logger.info("No parser for doc_type '%s' — using vision fallback", result.doc_type)
                return _VisionFallbackParser(known_type=result.doc_type)

        except Exception as exc:
            logger.warning("Classifier error (falling back to legacy): %s", exc)

        # ── Stage 2: Legacy can_parse() chain ─────────────────────────────────
        logger.info("Using legacy can_parse() chain for %s", filepath)
        for parser in _LEGACY_PARSERS:
            try:
                if parser.can_parse(filepath):
                    return parser
            except Exception:
                continue

        return _VisionFallbackParser()

    def parse(self, filepath: str) -> ParsedDocument:
        """Parse a file using the best available parser."""
        if not filepath:
            doc = ParsedDocument(doc_type="unknown", filename=filepath or "")
            doc.parse_errors.append("Empty filepath provided")
            return doc
        parser = self.get_parser(filepath)
        try:
            return parser.parse(filepath)
        except Exception as exc:
            doc = ParsedDocument(doc_type="unknown", filename=filepath)
            doc.parse_errors.append(
                f"Registry parse error: {exc}\n{traceback.format_exc()}"
            )
            return doc


class _VisionFallbackParser(BaseParser):
    """Last-resort parser: OCR via vision model with generic schema."""

    def __init__(self, known_type: str = "unknown") -> None:
        self._known_type = known_type

    def can_parse(self, filepath: str) -> bool:
        return True

    def parse(self, filepath: str) -> ParsedDocument:
        doc = ParsedDocument(
            doc_type=self._known_type or "unknown_vision_fallback",
            filename=filepath,
        )
        try:
            from inditr.parsers.vision import parse_with_vision
            from pydantic import BaseModel

            class GenericSchema(BaseModel):
                document_type: str = ""
                key_values: dict = {}

            vision_doc = parse_with_vision(filepath, self._known_type or "unknown", GenericSchema)
            doc.fields.update(vision_doc.fields)
            doc.parse_errors.extend(vision_doc.parse_errors)
        except Exception as exc:
            doc.parse_errors.append(f"Vision fallback error: {exc}")
        return doc
