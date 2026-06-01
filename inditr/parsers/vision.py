"""
Vision-based PDF parser using NVIDIA Nemotron 2 Nano VL on DeepInfra.
Used as fallback when structured parsers fail.
All LLM calls in IndITR are routed through this module or graph/nodes.
Parsers NEVER raise unhandled exceptions.
"""
from __future__ import annotations
import base64
import json
import re
import traceback
from typing import Type, TypeVar

from pydantic import BaseModel

from inditr.models.documents import ExtractedField, ParsedDocument

T = TypeVar("T", bound=BaseModel)

_VISION_CONFIDENCE = 0.80


def _pdf_to_base64_images(filepath: str, max_pages: int = 5) -> list[str]:
    """Convert PDF pages to base64-encoded JPEG strings."""
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(filepath, dpi=150, first_page=1, last_page=max_pages)
        b64_images = []
        for img in images:
            import io
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            b64_images.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
        return b64_images
    except Exception as exc:
        raise RuntimeError(f"PDF to image conversion failed: {exc}") from exc


def parse_with_vision(
    filepath: str,
    doc_type: str,
    extraction_schema: Type[T],
) -> ParsedDocument:
    """
    Parse a document using vision LLM as fallback.
    Returns ParsedDocument — never raises.
    """
    doc = ParsedDocument(doc_type=f"{doc_type}_vision", filename=filepath)

    try:
        import litellm
        from inditr.graph.llm import VISION_MODEL

        # Convert PDF to images
        try:
            b64_images = _pdf_to_base64_images(filepath)
        except Exception as exc:
            doc.parse_errors.append(f"Cannot convert PDF to images: {exc}")
            return doc

        if not b64_images:
            doc.parse_errors.append("No images extracted from PDF for vision parsing")
            return doc

        # Build schema description from Pydantic model
        schema_fields = list(extraction_schema.model_fields.keys())
        schema_json = extraction_schema.model_json_schema()

        prompt = (
            f"You are extracting structured data from an Indian tax document ({doc_type}). "
            f"Extract ONLY the following fields and return a valid JSON object with these keys: "
            f"{schema_fields}. "
            f"Return ONLY the JSON object, no explanation, no markdown fences. "
            f"If a field cannot be found, use null or 0 as appropriate."
        )

        # Build messages — text + image(s)
        content = [{"type": "text", "text": prompt}]
        for b64 in b64_images[:3]:  # limit to 3 pages for cost
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })

        response = litellm.completion(
            model=VISION_MODEL,
            messages=[{"role": "user", "content": content}],
            temperature=0.0,
            max_tokens=1024,
        )

        raw_text = response.choices[0].message.content or ""

        # Extract JSON from response
        json_text = raw_text.strip()
        if json_text.startswith("```"):
            json_text = re.sub(r"```[a-z]*\n?", "", json_text).replace("```", "").strip()

        try:
            parsed_json = json.loads(json_text)
            validated = extraction_schema(**parsed_json)

            # Store each field
            for field_name in schema_fields:
                val = getattr(validated, field_name, None)
                doc.fields[field_name] = ExtractedField(
                    value=val,
                    source_document=filepath,
                    source_section="vision_llm",
                    confidence=_VISION_CONFIDENCE,
                    raw_text=json_text[:200],
                )
        except (json.JSONDecodeError, Exception) as exc:
            doc.parse_errors.append(
                f"Vision response schema validation failed: {exc}. Raw: {raw_text[:200]}"
            )

    except Exception as exc:
        doc.parse_errors.append(f"Vision parsing error: {exc}\n{traceback.format_exc()}")

    return doc
