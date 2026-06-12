"""
Single Label Review page.
Upload one label image, fill in application fields, get AI verification.
"""

import streamlit as st
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.analyzer import (
    verify_label,
    get_media_type,
    TTB_FIELD_DESCRIPTIONS,
    GOVERNMENT_WARNING_CANONICAL,
    VerificationResult,
    FieldResult,
)

FIELD_DISPLAY_NAMES = {
    "brand_name": "Brand Name",
    "class_type": "Class / Type",
    "alcohol_content": "Alcohol Content (ABV)",
    "net_contents": "Net Contents",
    "bottler_name": "Bottler / Producer Name",
    "bottler_address": "Bottler / Producer Address",
    "country_of_origin": "Country of Origin",
    "government_warning": "Government Warning Statement",
}

STATUS_ICONS = {
    "pass": "✅",
    "fail": "❌",
    "warning": "⚠️",
    "not_checked": "—",
}

STATUS_COLORS = {
    "pass": "#10b981",
    "fail": "#ef4444",
    "warning": "#f59e0b",
    "not_checked": "#94a3b8",
}


def render():
    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown("""
    <div class='app-header'>
        <span class='app-title'>Label Verification</span>
        <span class='app-badge'>SINGLE REVIEW</span>
    </div>
    <div class='app-subtitle'>
        Upload a label image and enter the corresponding COLA application fields to check for compliance.
    </div>
    """, unsafe_allow_html=True)

    # ── API Key ───────────────────────────────────────────────────────────────
    with st.expander("⚙️ API Configuration", expanded="api_key" not in st.session_state):
        api_key = st.text_input(
            "Anthropic API Key",
            type="password",
            value=st.session_state.get("api_key", ""),
            help="Your Anthropic API key. Stored only in session memory — never logged or saved.",
            placeholder="sk-ant-..."
        )
        if api_key:
            st.session_state["api_key"] = api_key
            st.success("API key saved for this session.")

    st.markdown("---")

    # ── Main Layout ───────────────────────────────────────────────────────────
    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        st.markdown("#### 1 — Upload Label Image")
        uploaded_file = st.file_uploader(
            "Drag and drop or click to upload",
            type=["jpg", "jpeg", "png", "webp"],
            label_visibility="collapsed",
            key="single_upload"
        )

        if uploaded_file:
            st.image(uploaded_file, caption=uploaded_file.name, use_container_width=True)
            st.caption(f"File: `{uploaded_file.name}` · {uploaded_file.size // 1024} KB")

    with col_right:
        st.markdown("#### 2 — Application Data")
        st.caption("Enter the values from the COLA application. Leave blank to skip that field.")

        app_data = {}

        app_data["brand_name"] = st.text_input(
            "Brand Name",
            placeholder="e.g., OLD TOM DISTILLERY",
            key="field_brand_name"
        )
        app_data["class_type"] = st.text_input(
            "Class / Type",
            placeholder="e.g., Kentucky Straight Bourbon Whiskey",
            key="field_class_type"
        )

        c1, c2 = st.columns(2)
        with c1:
            app_data["alcohol_content"] = st.text_input(
                "Alcohol Content (ABV)",
                placeholder="e.g., 45% Alc./Vol.",
                key="field_abv"
            )
        with c2:
            app_data["net_contents"] = st.text_input(
                "Net Contents",
                placeholder="e.g., 750 mL",
                key="field_net"
            )

        app_data["bottler_name"] = st.text_input(
            "Bottler / Producer Name",
            placeholder="e.g., Old Tom Distilling Co.",
            key="field_bottler_name"
        )
        app_data["bottler_address"] = st.text_input(
            "Bottler / Producer Address",
            placeholder="e.g., 123 Distillery Lane, Louisville, KY 40201",
            key="field_bottler_addr"
        )
        app_data["country_of_origin"] = st.text_input(
            "Country of Origin (imports only)",
            placeholder="e.g., Scotland",
            key="field_country"
        )

        with st.expander("Government Warning Statement", expanded=False):
            st.caption("Leave blank to auto-check against TTB canonical warning.")
            app_data["government_warning"] = st.text_area(
                "Warning text from application",
                placeholder=GOVERNMENT_WARNING_CANONICAL,
                height=100,
                key="field_warning",
                label_visibility="collapsed"
            )
            # If blank, auto-fill canonical for checking
            if not app_data["government_warning"].strip():
                app_data["government_warning"] = GOVERNMENT_WARNING_CANONICAL

    st.markdown("---")

    # ── Submit ────────────────────────────────────────────────────────────────
    col_btn, col_note = st.columns([1, 3])
    with col_btn:
        run_check = st.button("🔍 Run Compliance Check", type="primary", use_container_width=True)
    with col_note:
        st.caption("Typically completes in under 5 seconds. Results are not stored.")

    # ── Results ───────────────────────────────────────────────────────────────
    if run_check:
        if not uploaded_file:
            st.error("Please upload a label image.")
            return
        if not st.session_state.get("api_key"):
            st.error("Please enter your Anthropic API key above.")
            return

        image_bytes = uploaded_file.read()
        media_type = get_media_type(uploaded_file.name)

        with st.spinner("Analyzing label..."):
            try:
                result = verify_label(
                    image_bytes=image_bytes,
                    application_data=app_data,
                    api_key=st.session_state["api_key"],
                    media_type=media_type,
                )
                _render_results(result)
            except Exception as e:
                st.error(f"Analysis failed: {str(e)}")
                st.caption("Check that your API key is valid and has sufficient credits.")


def _render_results(result: VerificationResult):
    st.markdown("---")
    st.markdown("#### 3 — Compliance Review Results")

    # Verdict banner
    if result.verdict == "APPROVED":
        st.markdown(
            "<div class='verdict-pass'>✅ &nbsp; APPROVED — All checked fields match</div>",
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            "<div class='verdict-fail'>❌ &nbsp; REJECTED — One or more fields failed verification</div>",
            unsafe_allow_html=True
        )

    st.caption(f"Processing time: {result.processing_time_ms}ms")

    if result.extraction_notes:
        st.warning(f"**Image quality note:** {result.extraction_notes}")

    st.markdown("<br>", unsafe_allow_html=True)

    # Field-by-field breakdown
    for fr in result.field_results:
        if fr.status == "not_checked":
            continue  # Don't clutter UI with skipped fields

        display_name = FIELD_DISPLAY_NAMES.get(fr.field, fr.field.replace("_", " ").title())
        icon = STATUS_ICONS[fr.status]
        color = STATUS_COLORS[fr.status]

        card_class = {
            "pass": "result-card result-pass",
            "fail": "result-card result-fail",
            "warning": "result-card result-warn",
        }.get(fr.status, "result-card")

        label_display = fr.label_value or "*not detected*"
        app_display = fr.application_value or "*not provided*"

        st.markdown(f"""
        <div class='{card_class}'>
            <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;'>
                <span style='font-weight:600; font-size:0.95rem; color:#1e293b;'>{display_name}</span>
                <span style='color:{color}; font-weight:700; font-size:0.9rem;'>{icon} {fr.status.upper()}</span>
            </div>
            <div style='display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:8px;'>
                <div>
                    <div class='field-label'>On Label</div>
                    <div class='field-value'>{label_display}</div>
                </div>
                <div>
                    <div class='field-label'>In Application</div>
                    <div class='field-value'>{app_display}</div>
                </div>
            </div>
            <div style='font-size:0.82rem; color:#64748b;'>{fr.message}</div>
        </div>
        """, unsafe_allow_html=True)

    # Raw extraction (collapsed)
    with st.expander("View raw AI extraction", expanded=False):
        st.json(result.raw_extracted)
