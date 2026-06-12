import streamlit as st
import anthropic
import base64
import json
import re
import time
import pandas as pd
from dataclasses import dataclass
from typing import Optional

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="TTB Label Verifier",
    page_icon="🏷️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    [data-testid="stSidebar"] { background-color: #0f1923; border-right: 1px solid #1e2d3d; }
    [data-testid="stSidebar"] * { color: #c9d8e8 !important; }
    .main .block-container { padding-top: 2rem; max-width: 1100px; }
    .app-title { font-size: 1.6rem; font-weight: 700; color: #0f1923; letter-spacing: -0.5px; }
    .app-badge { font-family: 'DM Mono', monospace; font-size: 0.7rem; background: #e8f0fe; color: #1a56db; padding: 2px 8px; border-radius: 3px; font-weight: 500; }
    .app-subtitle { color: #64748b; font-size: 0.9rem; margin-bottom: 2rem; }
    .result-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1.25rem 1.5rem; margin-bottom: 1rem; }
    .result-pass { border-left: 4px solid #10b981; }
    .result-fail { border-left: 4px solid #ef4444; }
    .result-warn { border-left: 4px solid #f59e0b; }
    .field-label { font-family: 'DM Mono', monospace; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; color: #94a3b8; margin-bottom: 2px; }
    .field-value { font-size: 0.95rem; color: #1e293b; font-weight: 500; }
    .verdict-pass { background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px; padding: 1rem 1.5rem; color: #065f46; font-weight: 600; font-size: 1.1rem; text-align: center; }
    .verdict-fail { background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 1rem 1.5rem; color: #991b1b; font-weight: 600; font-size: 1.1rem; text-align: center; }
    [data-testid="stFileUploader"] { border: 2px dashed #cbd5e1; border-radius: 8px; padding: 0.5rem; }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────

GOVERNMENT_WARNING_CANONICAL = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)

REQUIRED_WARNING_PREFIX = "GOVERNMENT WARNING:"

TTB_FIELDS = {
    "brand_name": "Brand Name",
    "class_type": "Class / Type",
    "alcohol_content": "Alcohol Content (ABV)",
    "net_contents": "Net Contents",
    "bottler_name": "Bottler / Producer Name",
    "bottler_address": "Bottler / Producer Address",
    "country_of_origin": "Country of Origin",
    "government_warning": "Government Warning Statement",
}

EXTRACTION_PROMPT = """You are an expert TTB label compliance analyst.

Examine this alcohol beverage label image and extract ALL visible text fields.

Return ONLY a valid JSON object with these exact keys. Use null if a field is not visible.

{
  "brand_name": "exact text as shown",
  "class_type": "exact class/type designation",
  "alcohol_content": "exact ABV as shown",
  "net_contents": "exact net contents as shown",
  "bottler_name": "exact bottler/producer name",
  "bottler_address": "exact bottler/producer address",
  "country_of_origin": "country of origin or null",
  "government_warning": "COMPLETE government warning text verbatim",
  "extraction_notes": "any image quality or legibility issues"
}

RULES:
- Extract text EXACTLY as it appears — preserve capitalization and punctuation
- For government_warning: capture the ENTIRE statement word for word
- Do not guess — only report what is clearly visible
- Return ONLY the JSON, no other text"""

# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class FieldResult:
    field: str
    label_value: Optional[str]
    application_value: Optional[str]
    status: str
    message: str

@dataclass
class VerificationResult:
    verdict: str
    field_results: list
    extraction_notes: str
    processing_time_ms: int
    raw_extracted: dict

# ── Core logic ────────────────────────────────────────────────────────────────

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return text

def check_field(field_name, label_value, application_value):
    if not application_value or str(application_value).strip() == "":
        return FieldResult(field_name, label_value, None, "not_checked", "Not provided — skipped.")

    if not label_value or str(label_value).strip() == "":
        return FieldResult(field_name, None, application_value, "fail",
                           f"Not detected on label. Application lists: '{application_value}'")

    if field_name == "government_warning":
        if not label_value.startswith(REQUIRED_WARNING_PREFIX):
            if label_value.upper().startswith(REQUIRED_WARNING_PREFIX):
                return FieldResult(field_name, label_value, application_value, "fail",
                                   f"'GOVERNMENT WARNING:' must be ALL CAPS. Found: '{label_value[:30]}...'")
            return FieldResult(field_name, label_value, application_value, "fail",
                               "Required 'GOVERNMENT WARNING:' prefix not found on label.")
        if normalize_text(label_value) == normalize_text(GOVERNMENT_WARNING_CANONICAL):
            return FieldResult(field_name, label_value, application_value, "pass",
                               "Government warning matches TTB canonical text exactly.")
        return FieldResult(field_name, label_value, application_value, "fail",
                           "Government warning text does not match TTB-required statement.")

    label_norm = normalize_text(label_value)
    app_norm = normalize_text(application_value)

    if label_norm == app_norm:
        return FieldResult(field_name, label_value, application_value, "pass", "Match confirmed.")
    if label_norm in app_norm or app_norm in label_norm:
        return FieldResult(field_name, label_value, application_value, "warning",
                           f"Partial match — review recommended. Label: '{label_value}' vs Application: '{application_value}'")
    return FieldResult(field_name, label_value, application_value, "fail",
                       f"Mismatch. Label: '{label_value}' vs Application: '{application_value}'")

def verify_label(image_bytes, application_data, api_key, media_type="image/jpeg"):
    start = time.time()
    client = anthropic.Anthropic(api_key=api_key)
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                {"type": "text", "text": EXTRACTION_PROMPT}
            ]
        }]
    )

    response_text = message.content[0].text.strip()
    response_text = re.sub(r"^```json\s*", "", response_text)
    response_text = re.sub(r"\s*```$", "", response_text)
    extracted = json.loads(response_text)

    field_results = []
    for field_name in TTB_FIELDS.keys():
        result = check_field(field_name, extracted.get(field_name), application_data.get(field_name, ""))
        field_results.append(result)

    has_failure = any(r.status == "fail" for r in field_results if r.status != "not_checked")
    verdict = "REJECTED" if has_failure else "APPROVED"

    return VerificationResult(
        verdict=verdict,
        field_results=field_results,
        extraction_notes=extracted.get("extraction_notes") or "",
        processing_time_ms=int((time.time() - start) * 1000),
        raw_extracted=extracted,
    )

def get_media_type(filename):
    ext = filename.lower().split(".")[-1]
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")

# ── UI helpers ────────────────────────────────────────────────────────────────

STATUS_ICONS = {"pass": "✅", "fail": "❌", "warning": "⚠️", "not_checked": "—"}
STATUS_COLORS = {"pass": "#10b981", "fail": "#ef4444", "warning": "#f59e0b", "not_checked": "#94a3b8"}

def render_results(result):
    st.markdown("---")
    st.markdown("#### Compliance Review Results")

    if result.verdict == "APPROVED":
        st.markdown("<div class='verdict-pass'>✅ &nbsp; APPROVED — All checked fields match</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='verdict-fail'>❌ &nbsp; REJECTED — One or more fields failed verification</div>", unsafe_allow_html=True)

    st.caption(f"Processing time: {result.processing_time_ms}ms")

    if result.extraction_notes:
        st.warning(f"**Image quality note:** {result.extraction_notes}")

    st.markdown("<br>", unsafe_allow_html=True)

    for fr in result.field_results:
        if fr.status == "not_checked":
            continue
        display_name = TTB_FIELDS.get(fr.field, fr.field)
        icon = STATUS_ICONS[fr.status]
        color = STATUS_COLORS[fr.status]
        card_class = {"pass": "result-card result-pass", "fail": "result-card result-fail", "warning": "result-card result-warn"}.get(fr.status, "result-card")
        label_display = fr.label_value or "*not detected*"
        app_display = fr.application_value or "*not provided*"

        st.markdown(f"""
        <div class='{card_class}'>
            <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;'>
                <span style='font-weight:600; font-size:0.95rem; color:#1e293b;'>{display_name}</span>
                <span style='color:{color}; font-weight:700;'>{icon} {fr.status.upper()}</span>
            </div>
            <div style='display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:8px;'>
                <div><div class='field-label'>On Label</div><div class='field-value'>{label_display}</div></div>
                <div><div class='field-label'>In Application</div><div class='field-value'>{app_display}</div></div>
            </div>
            <div style='font-size:0.82rem; color:#64748b;'>{fr.message}</div>
        </div>
        """, unsafe_allow_html=True)

    with st.expander("View raw AI extraction"):
        st.json(result.raw_extracted)

# ── API key widget ────────────────────────────────────────────────────────────

def api_key_widget(key_suffix=""):
    with st.expander("⚙️ API Configuration", expanded="api_key" not in st.session_state):
        api_key = st.text_input("Anthropic API Key", type="password",
                                value=st.session_state.get("api_key", ""),
                                key=f"api_input_{key_suffix}", placeholder="sk-ant-...")
        if api_key:
            st.session_state["api_key"] = api_key
            st.success("API key saved for this session.")

# ── Pages ─────────────────────────────────────────────────────────────────────

def page_single_label():
    st.markdown("<div style='margin-bottom:0.25rem;'><span class='app-title'>Label Verification</span></div>", unsafe_allow_html=True)
    st.markdown("<div class='app-subtitle'>Upload a label image and enter the COLA application fields to check compliance.</div>", unsafe_allow_html=True)

    api_key_widget("single")
    st.markdown("---")

    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        st.markdown("#### 1 — Upload Label Image")
        uploaded_file = st.file_uploader("Upload label", type=["jpg", "jpeg", "png", "webp"],
                                          label_visibility="collapsed", key="single_upload")
        if uploaded_file:
            st.image(uploaded_file, use_container_width=True)
            st.caption(f"`{uploaded_file.name}` · {uploaded_file.size // 1024} KB")

    with col_right:
        st.markdown("#### 2 — Application Data")
        st.caption("Enter values from the COLA application. Leave blank to skip that field.")

        app_data = {}
        app_data["brand_name"] = st.text_input("Brand Name", placeholder="e.g., OLD TOM DISTILLERY")
        app_data["class_type"] = st.text_input("Class / Type", placeholder="e.g., Kentucky Straight Bourbon Whiskey")
        c1, c2 = st.columns(2)
        with c1:
            app_data["alcohol_content"] = st.text_input("Alcohol Content (ABV)", placeholder="e.g., 45% Alc./Vol.")
        with c2:
            app_data["net_contents"] = st.text_input("Net Contents", placeholder="e.g., 750 mL")
        app_data["bottler_name"] = st.text_input("Bottler / Producer Name", placeholder="e.g., Old Tom Distilling Co.")
        app_data["bottler_address"] = st.text_input("Bottler / Producer Address", placeholder="e.g., 123 Distillery Lane, Louisville, KY")
        app_data["country_of_origin"] = st.text_input("Country of Origin (imports only)", placeholder="e.g., Scotland")

        with st.expander("Government Warning Statement"):
            st.caption("Leave blank to auto-check against TTB canonical warning.")
            app_data["government_warning"] = st.text_area("Warning text", placeholder=GOVERNMENT_WARNING_CANONICAL,
                                                           height=80, label_visibility="collapsed")
            if not app_data["government_warning"].strip():
                app_data["government_warning"] = GOVERNMENT_WARNING_CANONICAL

    st.markdown("---")
    run_check = st.button("🔍 Run Compliance Check", type="primary")

    if run_check:
        if not uploaded_file:
            st.error("Please upload a label image.")
            return
        if not st.session_state.get("api_key"):
            st.error("Please enter your Anthropic API key above.")
            return
        with st.spinner("Analyzing label..."):
            try:
                result = verify_label(uploaded_file.read(), app_data,
                                      st.session_state["api_key"], get_media_type(uploaded_file.name))
                render_results(result)
            except Exception as e:
                st.error(f"Analysis failed: {str(e)}")


def page_batch():
    st.markdown("<div style='margin-bottom:0.25rem;'><span class='app-title'>Batch Label Review</span></div>", unsafe_allow_html=True)
    st.markdown("<div class='app-subtitle'>Upload multiple label images and a CSV of application data.</div>", unsafe_allow_html=True)

    api_key_widget("batch")
    st.markdown("---")

    SAMPLE_CSV = f"""filename,brand_name,class_type,alcohol_content,net_contents,bottler_name,bottler_address,country_of_origin,government_warning
label_001.jpg,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45% Alc./Vol. (90 Proof),750 mL,Old Tom Distilling Co.,123 Distillery Lane Louisville KY 40201,,{GOVERNMENT_WARNING_CANONICAL}
label_002.jpg,SILVER PEAK VODKA,Vodka,40% Alc./Vol. (80 Proof),1 L,Silver Peak Spirits LLC,456 Spirits Ave Denver CO 80202,,{GOVERNMENT_WARNING_CANONICAL}
"""

    with st.expander("📋 How to use batch review"):
        st.markdown("""
        1. Download the CSV template and fill in your application data — `filename` must match your image filenames exactly.
        2. Upload all label images.
        3. Upload your completed CSV.
        4. Click **Run Batch Review**.
        """)
        st.download_button("⬇️ Download CSV Template", data=SAMPLE_CSV,
                           file_name="ttb_batch_template.csv", mime="text/csv")

    st.markdown("---")
    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.markdown("#### 1 — Upload Label Images")
        uploaded_images = st.file_uploader("Upload images", type=["jpg", "jpeg", "png", "webp"],
                                            accept_multiple_files=True, label_visibility="collapsed")
        if uploaded_images:
            st.success(f"{len(uploaded_images)} image(s) uploaded")

    with col2:
        st.markdown("#### 2 — Upload Application CSV")
        uploaded_csv = st.file_uploader("Upload CSV", type=["csv"], label_visibility="collapsed")
        df = None
        if uploaded_csv:
            try:
                df = pd.read_csv(uploaded_csv)
                st.success(f"CSV loaded: {len(df)} application(s)")
                st.dataframe(df.head(3), use_container_width=True)
            except Exception as e:
                st.error(f"Could not parse CSV: {e}")

    st.markdown("---")

    if st.button("🔍 Run Batch Review", type="primary"):
        if not uploaded_images:
            st.error("Please upload label images.")
            return
        if df is None:
            st.error("Please upload a valid CSV.")
            return
        if not st.session_state.get("api_key"):
            st.error("Please enter your Anthropic API key.")
            return

        image_lookup = {f.name: f for f in uploaded_images}
        results_rows = []
        progress = st.progress(0, text="Starting...")
        total = len(df)

        for idx, row in df.iterrows():
            filename = str(row.get("filename", "")).strip()
            progress.progress((idx + 1) / total, text=f"Processing {idx+1}/{total}: {filename}")

            if filename not in image_lookup:
                results_rows.append({"filename": filename, "verdict": "ERROR", "brand_name": "",
                                     "failures": f"Image '{filename}' not found", "warnings": "—", "processing_ms": 0})
                continue

            img_file = image_lookup[filename]
            img_bytes = img_file.read()
            img_file.seek(0)

            app_data = {}
            for col in ["brand_name","class_type","alcohol_content","net_contents",
                        "bottler_name","bottler_address","country_of_origin","government_warning"]:
                val = row.get(col, "")
                app_data[col] = str(val) if pd.notna(val) and str(val).strip() else ""
            if not app_data.get("government_warning", "").strip():
                app_data["government_warning"] = GOVERNMENT_WARNING_CANONICAL

            try:
                result = verify_label(img_bytes, app_data, st.session_state["api_key"], get_media_type(filename))
                failures = [f"{r.field}: {r.message}" for r in result.field_results if r.status == "fail"]
                warnings = [f"{r.field}: {r.message}" for r in result.field_results if r.status == "warning"]
                results_rows.append({"filename": filename, "verdict": result.verdict,
                                     "brand_name": result.raw_extracted.get("brand_name", ""),
                                     "failures": "; ".join(failures) or "—",
                                     "warnings": "; ".join(warnings) or "—",
                                     "processing_ms": result.processing_time_ms})
            except Exception as e:
                results_rows.append({"filename": filename, "verdict": "ERROR", "brand_name": "",
                                     "failures": str(e), "warnings": "—", "processing_ms": 0})

        progress.progress(1.0, text="Complete!")
        results_df = pd.DataFrame(results_rows)
        approved = len(results_df[results_df["verdict"] == "APPROVED"])
        rejected = len(results_df[results_df["verdict"] == "REJECTED"])

        st.markdown("---")
        st.markdown("#### Results Summary")
        m1, m2, m3 = st.columns(3)
        m1.metric("Total", total)
        m2.metric("Approved", approved)
        m3.metric("Rejected", rejected)
        st.dataframe(results_df, use_container_width=True)
        st.download_button("⬇️ Download Results CSV", data=results_df.to_csv(index=False),
                           file_name="ttb_batch_results.csv", mime="text/csv", type="primary")


def page_about():
    st.markdown("<div style='margin-bottom:0.25rem;'><span class='app-title'>About This Tool</span></div>", unsafe_allow_html=True)
    st.markdown("<div class='app-subtitle'>Approach, technical decisions, and known limitations.</div>", unsafe_allow_html=True)

    st.markdown("""
## What This Tool Does

The TTB Label Verifier automates first-pass compliance checks for TTB Certificate of Label Approval (COLA) applications.
An agent uploads a label image and enters the corresponding application data. The tool uses Claude's vision capability
to extract every field from the label, then compares each against the application and flags mismatches.

---

## Technical Choices

| Decision | Choice | Rationale |
|---|---|---|
| AI model | Claude claude-sonnet-4-6 (vision) vs OCR + regex | LLM vision handles curved surfaces, glare, varied fonts without brittle rule engineering |
| Model tier | Sonnet over Opus | Sonnet hits the <5s target; Opus averages 7–9s — unusable per stakeholder feedback |
| Framework | Streamlit | End users are compliance agents, not developers. No frontend code needed. |
| Matching | Fuzzy for most fields; strict for government warning | Per-field strategy — fuzzy handles formatting variation; strict enforces a legal requirement |

---

## Field Validation Logic

**Government Warning — Strict**
- Must begin with `GOVERNMENT WARNING:` in ALL CAPS
- Must match TTB canonical text exactly (normalized whitespace)

**All Other Fields — Fuzzy Match**
- Lowercased, whitespace collapsed, smart quotes normalized
- Handles `STONE'S THROW` = `Stone's Throw` (per agent feedback)
- Partial match → WARNING status for human review, not auto-reject

---

## Beverage Type Coverage

| Field | Distilled Spirits | Wine | Beer |
|---|---|---|---|
| Brand name | Required | Required | Required |
| Class/type | Required | Required | Required |
| Alcohol content | Required | Required >14% | Not always required |
| Net contents | Required | Required | Required |
| Bottler name & address | Required | Required | Required |
| Country of origin | Imports | Imports | Imports |
| Government Warning | Required | Required | Required |

*Source: TTB guidelines at [ttb.gov](https://www.ttb.gov/labeling)*

The prototype applies common mandatory fields across all beverage types. ABV enforcement for beer
categories where TTB does not require it is a documented future enhancement.

---

## Network & Security Considerations

This prototype calls `api.anthropic.com` directly. In federal network environments where
outbound traffic to external ML endpoints is restricted, this call would fail.

**Production path:**
```
Agent Browser → Azure API Management Gateway (inside Treasury Azure Government boundary)
             → Anthropic API via approved egress
               — or —
               Azure AI Services (Anthropic on Azure Marketplace, FedRAMP boundary)
```

Treasury's existing Azure infrastructure (migrated 2019) is the natural home for this integration.
The API key is held in session memory only — never logged or stored.

---

## Error Handling

- **API failure:** Caught by try/except; plain-language error shown; no partial results displayed
- **Malformed AI response:** JSON parse exception caught; label marked as errored
- **Unreadable image:** Claude returns extraction_notes; all null fields → rejected with explanation
- **Missing CSV columns:** Validated before batch processing begins
- **File not found in batch:** Row marked ERROR; processing continues for remaining labels

---

## Assumptions & Trade-offs

- **No COLA integration:** Standalone proof-of-concept. Production would integrate with COLA's .NET data layer.
- **No data retention:** In-memory only. Document retention policies needed for production.
- **Sequential batch processing:** Simple and debuggable. Parallel processing is a future enhancement.
- **Agent judgment preserved:** Tool flags mismatches — agents make final determinations.
- **Numeric unit equivalence:** `750ml` vs `750 mL` fuzzy-matches; `0.75 L` vs `750 mL` does not. Future work.

---

## Stakeholder Requirements Traceability

| Requirement | Source | Status | Implementation |
|---|---|---|---|
| Results in < 5 seconds | Sarah Chen | ✅ | Claude claude-sonnet-4-6, avg 2–4s |
| Batch upload | Sarah Chen / Janet (Seattle) | ✅ | Batch page with CSV + multi-image |
| Simple UI | Sarah Chen | ✅ | Streamlit, minimal chrome |
| Fuzzy field matching | Dave Morrison | ✅ | Normalize-then-compare |
| Agent judgment preserved | Dave Morrison | ✅ | WARNING routes to human review |
| Exact warning enforcement | Jenny Park | ✅ | Strict all-caps + canonical text |
| Buried warning detection | Jenny Park | ✅ | Vision model reads full image |
| Imperfect image handling | Jenny Park | ✅ | Claude vision + extraction_notes |
| No COLA integration | Marcus Williams | ✅ | Standalone prototype |
| No sensitive data stored | Marcus Williams | ✅ | In-memory only |
| Network/firewall | Marcus Williams | ⚠️ | Direct API call; Azure APIM path documented above |

---

## About the Developer

Built by Quinton Campbell — Department of the Treasury IT Specialist (AI) GS-15 take-home assessment.
Questions: [take-home-test@treasury.gov](mailto:take-home-test@treasury.gov)
    """)


# ── Navigation ────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🏷️ TTB Label Verifier")
    st.markdown("---")
    page = st.radio("Navigate",
                    ["Single Label Review", "Batch Upload", "About & Documentation"],
                    label_visibility="collapsed")
    st.markdown("---")
    st.markdown("""
    <div style='font-size:0.78rem; color:#8899aa; line-height:1.6;'>
    <strong>Prototype v1.0</strong><br>
    Built for Department of the Treasury<br>
    TTB Compliance Division<br><br>
    ⚠️ This is a proof-of-concept.<br>
    Not for production use.
    </div>
    """, unsafe_allow_html=True)

if page == "Single Label Review":
    page_single_label()
elif page == "Batch Upload":
    page_batch()
elif page == "About & Documentation":
    page_about()
