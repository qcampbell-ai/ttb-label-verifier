"""
Core AI engine for TTB label analysis.
Uses Claude claude-sonnet-4-6 with vision to extract and verify label fields.
"""

import anthropic
import base64
import json
import re
import time
from dataclasses import dataclass
from typing import Optional
from io import BytesIO

# ── Constants ────────────────────────────────────────────────────────────────

GOVERNMENT_WARNING_CANONICAL = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)

REQUIRED_WARNING_PREFIX = "GOVERNMENT WARNING:"

TTB_FIELD_DESCRIPTIONS = {
    "brand_name": "Brand name of the product",
    "class_type": "Class and type designation (e.g., Kentucky Straight Bourbon Whiskey)",
    "alcohol_content": "Alcohol by volume percentage (ABV)",
    "net_contents": "Net contents / bottle size (e.g., 750 mL)",
    "bottler_name": "Name of bottler or producer",
    "bottler_address": "Address of bottler or producer",
    "country_of_origin": "Country of origin (required for imports)",
    "government_warning": "Full government health warning statement",
}

EXTRACTION_PROMPT = """You are an expert TTB (Alcohol and Tobacco Tax and Trade Bureau) label compliance analyst.

Carefully examine this alcohol beverage label image and extract ALL visible text fields.

Return ONLY a valid JSON object with these exact keys. If a field is not visible or not present on the label, use null.

{
  "brand_name": "exact text as shown on label",
  "class_type": "exact class/type designation",
  "alcohol_content": "exact ABV as shown (e.g., '45% Alc./Vol. (90 Proof)')",
  "net_contents": "exact net contents as shown (e.g., '750 mL')",
  "bottler_name": "exact bottler/producer name",
  "bottler_address": "exact bottler/producer address",
  "country_of_origin": "country of origin if shown, otherwise null",
  "government_warning": "COMPLETE government warning text verbatim — every single word, exactly as printed",
  "extraction_notes": "any issues with image quality, legibility, or unusual label elements"
}

CRITICAL RULES:
- Extract text EXACTLY as it appears — preserve capitalization, punctuation, spacing
- For government_warning: capture the ENTIRE warning statement word for word
- If text is partially obscured or unclear, note it in extraction_notes
- Do not infer or guess values — only report what is clearly visible
- Return ONLY the JSON, no other text"""


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class FieldResult:
    field: str
    label_value: Optional[str]
    application_value: Optional[str]
    status: str  # "pass", "fail", "warning", "not_checked"
    message: str


@dataclass
class VerificationResult:
    verdict: str  # "APPROVED" or "REJECTED"
    field_results: list[FieldResult]
    extraction_notes: str
    processing_time_ms: int
    raw_extracted: dict


# ── Core Functions ────────────────────────────────────────────────────────────

def encode_image(image_bytes: bytes, media_type: str = "image/jpeg") -> str:
    """Base64-encode image bytes for Claude API."""
    return base64.standard_b64encode(image_bytes).decode("utf-8")


def extract_label_fields(image_bytes: bytes, api_key: str, media_type: str = "image/jpeg") -> dict:
    """
    Call Claude vision API to extract all text fields from the label image.
    Returns parsed dict of extracted fields.
    """
    client = anthropic.Anthropic(api_key=api_key)

    image_data = encode_image(image_bytes, media_type)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": EXTRACTION_PROMPT
                    }
                ],
            }
        ],
    )

    response_text = message.content[0].text.strip()

    # Strip markdown fences if present
    response_text = re.sub(r"^```json\s*", "", response_text)
    response_text = re.sub(r"\s*```$", "", response_text)

    return json.loads(response_text)


def normalize_text(text: str) -> str:
    """Normalize text for fuzzy comparison: lowercase, collapse whitespace, strip punctuation variance."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    # Normalize common punctuation variants
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return text


def check_field(
    field_name: str,
    label_value: Optional[str],
    application_value: Optional[str],
) -> FieldResult:
    """
    Compare a single extracted label field against the application-submitted value.
    Returns a FieldResult with status and human-readable message.
    """

    # Field not submitted in application — skip check
    if not application_value or application_value.strip() == "":
        return FieldResult(
            field=field_name,
            label_value=label_value,
            application_value=None,
            status="not_checked",
            message="Not provided in application — skipped."
        )

    # Field not found on label
    if not label_value or label_value.strip() == "":
        return FieldResult(
            field=field_name,
            label_value=None,
            application_value=application_value,
            status="fail",
            message=f"Field not detected on label, but application lists: '{application_value}'"
        )

    # Government warning: strict exact match check (per Jenny's note — must be exact)
    if field_name == "government_warning":
        return _check_government_warning(label_value, application_value)

    # All other fields: fuzzy match (per Dave's note — STONE'S THROW = Stone's Throw)
    label_norm = normalize_text(label_value)
    app_norm = normalize_text(application_value)

    if label_norm == app_norm:
        return FieldResult(
            field=field_name,
            label_value=label_value,
            application_value=application_value,
            status="pass",
            message="Match confirmed."
        )

    # Check if one contains the other (handles minor formatting differences)
    if label_norm in app_norm or app_norm in label_norm:
        return FieldResult(
            field=field_name,
            label_value=label_value,
            application_value=application_value,
            status="warning",
            message=f"Partial match — review recommended. Label: '{label_value}' vs Application: '{application_value}'"
        )

    return FieldResult(
        field=field_name,
        label_value=label_value,
        application_value=application_value,
        status="fail",
        message=f"Mismatch detected. Label: '{label_value}' vs Application: '{application_value}'"
    )


def _check_government_warning(label_value: str, application_value: str) -> FieldResult:
    """
    Strict government warning validation.
    - Must start with 'GOVERNMENT WARNING:' in ALL CAPS
    - Full text must match canonical warning (case-insensitive for body, strict for prefix)
    """
    field_name = "government_warning"

    # Check for required ALL CAPS prefix
    if not label_value.startswith(REQUIRED_WARNING_PREFIX):
        # Check if it exists but wrong case
        if label_value.upper().startswith(REQUIRED_WARNING_PREFIX):
            return FieldResult(
                field=field_name,
                label_value=label_value,
                application_value=application_value,
                status="fail",
                message=f"'GOVERNMENT WARNING:' prefix must be in ALL CAPS. Found: '{label_value[:25]}...'"
            )
        return FieldResult(
            field=field_name,
            label_value=label_value,
            application_value=application_value,
            status="fail",
            message="Required 'GOVERNMENT WARNING:' prefix not found on label."
        )

    # Compare full warning text (normalized, case-insensitive on body)
    label_norm = normalize_text(label_value)
    canonical_norm = normalize_text(GOVERNMENT_WARNING_CANONICAL)

    if label_norm == canonical_norm:
        return FieldResult(
            field=field_name,
            label_value=label_value,
            application_value=application_value,
            status="pass",
            message="Government warning text matches TTB canonical requirement exactly."
        )

    # Check prefix is correct but body differs
    return FieldResult(
        field=field_name,
        label_value=label_value,
        application_value=application_value,
        status="fail",
        message="Government warning text does not match TTB-required statement. Non-standard wording detected."
    )


def verify_label(
    image_bytes: bytes,
    application_data: dict,
    api_key: str,
    media_type: str = "image/jpeg",
) -> VerificationResult:
    """
    Main entry point: extract label fields and verify against application data.

    Args:
        image_bytes: Raw image bytes of the label
        application_data: Dict of fields submitted in the COLA application
        api_key: Anthropic API key
        media_type: Image MIME type

    Returns:
        VerificationResult with per-field results and overall verdict
    """
    start_time = time.time()

    # Step 1: Extract fields from image via AI
    extracted = extract_label_fields(image_bytes, api_key, media_type)

    # Step 2: Check each field
    field_results = []
    for field_name in TTB_FIELD_DESCRIPTIONS.keys():
        label_val = extracted.get(field_name)
        app_val = application_data.get(field_name)

        result = check_field(field_name, label_val, app_val)
        field_results.append(result)

    # Step 3: Determine overall verdict
    # Any "fail" on a submitted field → REJECTED
    has_failure = any(
        r.status == "fail"
        for r in field_results
        if r.status != "not_checked"
    )
    verdict = "REJECTED" if has_failure else "APPROVED"

    processing_time_ms = int((time.time() - start_time) * 1000)

    return VerificationResult(
        verdict=verdict,
        field_results=field_results,
        extraction_notes=extracted.get("extraction_notes") or "",
        processing_time_ms=processing_time_ms,
        raw_extracted=extracted,
    )


def get_media_type(filename: str) -> str:
    """Infer MIME type from filename extension."""
    ext = filename.lower().split(".")[-1]
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(ext, "image/jpeg")
