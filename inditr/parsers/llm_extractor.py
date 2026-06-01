"""
LLM-based document field extractor.

Replaces per-document regex pattern lists with a single LLM call that
understands label variations, context, and abbreviations natively.

Flow:
    raw text (from pdfplumber)
        → LLM call with JSON schema description
        → JSON response
        → Pydantic schema validation   ← type safety, coercion
        → (schema_instance, per_field_confidences)

LIMITATION: The extractor cannot self-verify. A hallucinated-but-plausible
number passes through here without detection. That is caught (partially) by
the validator's Python cross-checks and human review for low-confidence fields.
The LLM reviewer in llm_validator catches semantic implausibility but NOT
numeric accuracy against the source document.
"""
from __future__ import annotations
import json
import logging
import re
from typing import Any, Type, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Confidence assigned to a field the LLM returned a non-null value for.
# 0.80 (not 0.90) — deliberately below the 0.85 human-review threshold so
# LLM-extracted fields go to human_doc_review by default unless Python
# cross-checks confirm the value is internally consistent.
# Raise to 0.90 only after a cross-check explicitly validates the field.
_LLM_FOUND_CONF = 0.80
_LLM_MISSING_CONF = 0.0

# Max characters of document text sent to LLM.
# Form 16 Part A + Part B together can run 6-10 pages (~14,000 chars).
# Truncating at 8000 frequently cuts off Part B (which contains all deductions).
# 32,000 chars comfortably covers combined Part A+B PDFs (Part A quarterly tables
# can be 12-15K chars; Part B computation is another 8-12K).
# Gemma 4 / Nemotron 3 both have ≥128K context windows — 32K is safe.
_MAX_TEXT_CHARS = 32_000


def _build_prompt(text: str, schema_cls: Type[BaseModel], doc_hint: str) -> str:
    """Build extraction prompt with field descriptions from the schema."""
    lines: list[str] = []
    for name, field_info in schema_cls.model_fields.items():
        desc = field_info.description or name.replace("_", " ").title()
        annotation = str(field_info.annotation)
        ftype = "number (float)" if any(t in annotation for t in ("float", "int")) else "string"
        lines.append(f"  {name} ({ftype}): {desc}")

    fields_block = "\n".join(lines)
    doc_text = text[:_MAX_TEXT_CHARS]

    return f"""You are a document extraction agent for Indian income tax documents.
Document type: {doc_hint}

Extract the fields listed below from the document text.

STRICT RULES:
1. Return ONLY a valid JSON object — no explanation, no markdown fences
2. Return null for any field not explicitly present in the document — NEVER guess or infer
3. Monetary amounts: numeric value only, no currency symbols, no commas (e.g. 850000.0)
4. TAN format: 10-character alphanumeric (e.g. "MUMX12345Y")
5. PAN format: 10-character alphanumeric (e.g. "ABCDE1234F")
6. Financial year: "YYYY-YY" format (e.g. "2025-26")
7. If the same field appears multiple times, use the final/total figure

Fields to extract:
{fields_block}

Document text:
---
{doc_text}
---

JSON:"""


def _parse_json_from_response(raw: str) -> dict[str, Any]:
    """
    Extract a JSON object from LLM response text.
    Handles markdown code fences and extra prose around the JSON.
    """
    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    # Direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Find the first {...} block (handles models that add explanation after)
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse JSON from LLM response (first 300 chars): %s", raw[:300])
    return {}


def extract_fields(
    text: str,
    schema_cls: Type[T],
    doc_hint: str = "Indian income tax document",
) -> tuple[T, dict[str, float]]:
    """
    Use the configured LLM to extract structured fields from document text.

    Args:
        text:       Raw text extracted from the document (via pdfplumber or similar).
        schema_cls: Pydantic model class defining the fields to extract.
        doc_hint:   Human-readable document type description for the prompt.

    Returns:
        (schema_instance, confidence_per_field)
        - Fields the LLM returned → value in schema, _LLM_FOUND_CONF in confidence.
        - Fields the LLM returned null → None in schema, 0.0 in confidence.
        - On total failure → empty schema instance, all confidences 0.0.
    """
    import litellm
    from inditr.graph.llm import MODEL

    prompt = _build_prompt(text, schema_cls, doc_hint)
    raw_response = ""

    try:
        response = litellm.completion(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,   # deterministic — extraction is not creative
            max_tokens=1024,
        )
        raw_response = response.choices[0].message.content or ""
    except Exception as exc:
        logger.error("LLM extraction call failed: %s", exc)

    extracted_dict = _parse_json_from_response(raw_response)

    # Per-field confidence: found → 0.90, null/missing → 0.0
    confidences: dict[str, float] = {
        name: (_LLM_FOUND_CONF if extracted_dict.get(name) is not None else _LLM_MISSING_CONF)
        for name in schema_cls.model_fields
    }

    # Pydantic validation — coerces types, strips invalid formats
    try:
        instance = schema_cls.model_validate(extracted_dict)
    except Exception as exc:
        logger.warning("Pydantic validation of LLM extraction failed: %s", exc)
        instance = schema_cls()
        confidences = {name: 0.0 for name in schema_cls.model_fields}

    return instance, confidences
