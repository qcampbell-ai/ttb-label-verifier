"""
Batch Upload Review page.
Upload multiple label images + a CSV of application data.
Process all in sequence and produce a downloadable results report.
"""

import streamlit as st
import pandas as pd
import io
from analyzer import (
    verify_label,
    get_media_type,
    GOVERNMENT_WARNING_CANONICAL,
)

EXPECTED_CSV_COLUMNS = [
    "filename",
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "bottler_name",
    "bottler_address",
    "country_of_origin",
    "government_warning",
]

SAMPLE_CSV = """filename,brand_name,class_type,alcohol_content,net_contents,bottler_name,bottler_address,country_of_origin,government_warning
label_001.jpg,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45% Alc./Vol. (90 Proof),750 mL,Old Tom Distilling Co.,123 Distillery Lane Louisville KY 40201,,{warning}
label_002.jpg,SILVER PEAK VODKA,Vodka,40% Alc./Vol. (80 Proof),1 L,Silver Peak Spirits LLC,456 Spirits Ave Denver CO 80202,,{warning}
""".format(warning=GOVERNMENT_WARNING_CANONICAL)


def render():
    st.markdown("""
    <div class='app-header'>
        <span class='app-title'>Batch Label Review</span>
        <span class='app-badge'>BULK PROCESSING</span>
    </div>
    <div class='app-subtitle'>
        Upload multiple label images and a CSV of application data to review in bulk.
        Results are downloadable as a report.
    </div>
    """, unsafe_allow_html=True)

    # ── API Key ───────────────────────────────────────────────────────────────
    with st.expander("⚙️ API Configuration", expanded="api_key" not in st.session_state):
        api_key = st.text_input(
            "Anthropic API Key",
            type="password",
            value=st.session_state.get("api_key", ""),
            key="batch_api_key",
            placeholder="sk-ant-..."
        )
        if api_key:
            st.session_state["api_key"] = api_key
            st.success("API key saved for this session.")

    st.markdown("---")

    # ── Instructions ──────────────────────────────────────────────────────────
    with st.expander("📋 How to use batch review", expanded=False):
        st.markdown("""
        **Step 1:** Download the CSV template below and fill in your application data.
        - The `filename` column must match your uploaded image filenames exactly.
        - Leave `government_warning` blank to auto-check against the TTB canonical warning.

        **Step 2:** Upload all your label images (JPG, PNG, WebP).

        **Step 3:** Upload your completed CSV.

        **Step 4:** Click **Run Batch Review**. Results will appear in a table and can be downloaded.

        > **Tip:** For large batches (200+ labels), processing takes approximately 3–5 seconds per label.
        """)
        st.download_button(
            "⬇️ Download CSV Template",
            data=SAMPLE_CSV,
            file_name="ttb_batch_template.csv",
            mime="text/csv",
        )

    st.markdown("---")

    # ── Upload Section ────────────────────────────────────────────────────────
    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.markdown("#### 1 — Upload Label Images")
        uploaded_images = st.file_uploader(
            "Upload label images",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            label_visibility="collapsed",
            key="batch_images"
        )
        if uploaded_images:
            st.success(f"{len(uploaded_images)} image(s) uploaded")
            with st.expander("Preview uploaded images"):
                cols = st.columns(3)
                for i, img in enumerate(uploaded_images[:9]):  # preview up to 9
                    with cols[i % 3]:
                        st.image(img, caption=img.name, use_container_width=True)
                if len(uploaded_images) > 9:
                    st.caption(f"... and {len(uploaded_images) - 9} more")

    with col2:
        st.markdown("#### 2 — Upload Application CSV")
        uploaded_csv = st.file_uploader(
            "Upload CSV",
            type=["csv"],
            label_visibility="collapsed",
            key="batch_csv"
        )

        if uploaded_csv:
            try:
                df = pd.read_csv(uploaded_csv)
                st.success(f"CSV loaded: {len(df)} application(s)")
                st.dataframe(df.head(5), use_container_width=True, height=200)

                missing_cols = [c for c in ["filename", "brand_name"] if c not in df.columns]
                if missing_cols:
                    st.error(f"CSV is missing required columns: {missing_cols}")
            except Exception as e:
                st.error(f"Could not parse CSV: {e}")
                df = None
        else:
            df = None

    st.markdown("---")

    # ── Run Batch ─────────────────────────────────────────────────────────────
    run_batch = st.button("🔍 Run Batch Review", type="primary")

    if run_batch:
        if not uploaded_images:
            st.error("Please upload label images.")
            return
        if df is None or uploaded_csv is None:
            st.error("Please upload a valid CSV file.")
            return
        if not st.session_state.get("api_key"):
            st.error("Please enter your Anthropic API key.")
            return

        # Build image lookup by filename
        image_lookup = {f.name: f for f in uploaded_images}

        results_rows = []
        progress_bar = st.progress(0, text="Starting batch review...")
        status_placeholder = st.empty()

        total = len(df)
        errors = 0

        for idx, row in df.iterrows():
            filename = str(row.get("filename", "")).strip()
            progress_pct = idx / total
            progress_bar.progress(progress_pct, text=f"Processing {idx + 1}/{total}: {filename}")
            status_placeholder.caption(f"⏳ Reviewing `{filename}`...")

            if filename not in image_lookup:
                results_rows.append({
                    "filename": filename,
                    "verdict": "ERROR",
                    "brand_name": row.get("brand_name", ""),
                    "details": f"Image file '{filename}' not found in upload.",
                    "processing_ms": 0,
                })
                errors += 1
                continue

            img_file = image_lookup[filename]
            img_bytes = img_file.read()
            img_file.seek(0)  # Reset for potential re-reads

            app_data = {}
            for col in EXPECTED_CSV_COLUMNS[1:]:
                val = row.get(col, "")
                app_data[col] = str(val) if pd.notna(val) and str(val).strip() else ""

            # Auto-fill canonical warning if blank
            if not app_data.get("government_warning", "").strip():
                app_data["government_warning"] = GOVERNMENT_WARNING_CANONICAL

            try:
                result = verify_label(
                    image_bytes=img_bytes,
                    application_data=app_data,
                    api_key=st.session_state["api_key"],
                    media_type=get_media_type(filename),
                )

                # Summarize failures
                failures = [
                    f"{r.field}: {r.message}"
                    for r in result.field_results
                    if r.status == "fail"
                ]
                warnings = [
                    f"{r.field}: {r.message}"
                    for r in result.field_results
                    if r.status == "warning"
                ]

                results_rows.append({
                    "filename": filename,
                    "verdict": result.verdict,
                    "brand_name": result.raw_extracted.get("brand_name", ""),
                    "failures": "; ".join(failures) if failures else "—",
                    "warnings": "; ".join(warnings) if warnings else "—",
                    "image_notes": result.extraction_notes or "—",
                    "processing_ms": result.processing_time_ms,
                })

            except Exception as e:
                errors += 1
                results_rows.append({
                    "filename": filename,
                    "verdict": "ERROR",
                    "brand_name": row.get("brand_name", ""),
                    "failures": f"Processing error: {str(e)}",
                    "warnings": "—",
                    "image_notes": "—",
                    "processing_ms": 0,
                })

        progress_bar.progress(1.0, text="Batch complete!")
        status_placeholder.empty()

        # ── Results Table ──────────────────────────────────────────────────────
        results_df = pd.DataFrame(results_rows)

        approved = len(results_df[results_df["verdict"] == "APPROVED"])
        rejected = len(results_df[results_df["verdict"] == "REJECTED"])

        st.markdown("---")
        st.markdown("#### Batch Results Summary")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Reviewed", total)
        m2.metric("Approved", approved, delta=None)
        m3.metric("Rejected", rejected, delta=None)
        m4.metric("Errors", errors, delta=None)

        st.markdown("<br>", unsafe_allow_html=True)

        # Color-code verdict column
        def style_verdict(val):
            if val == "APPROVED":
                return "color: #065f46; font-weight: 700;"
            elif val == "REJECTED":
                return "color: #991b1b; font-weight: 700;"
            return "color: #92400e; font-weight: 700;"

        st.dataframe(
            results_df,
            use_container_width=True,
            column_config={
                "verdict": st.column_config.TextColumn("Verdict", width=100),
                "filename": st.column_config.TextColumn("File", width=160),
                "brand_name": st.column_config.TextColumn("Brand Name", width=180),
                "failures": st.column_config.TextColumn("Failed Fields", width=300),
                "warnings": st.column_config.TextColumn("Warnings", width=200),
                "processing_ms": st.column_config.NumberColumn("Time (ms)", width=90),
            }
        )

        # Download results
        csv_out = results_df.to_csv(index=False)
        st.download_button(
            "⬇️ Download Results CSV",
            data=csv_out,
            file_name="ttb_batch_results.csv",
            mime="text/csv",
            type="primary",
        )"""
Batch Upload Review page.
Upload multiple label images + a CSV of application data.
Process all in sequence and produce a downloadable results report.
"""

import streamlit as st
import pandas as pd
import io
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.analyzer import (
    verify_label,
    get_media_type,
    GOVERNMENT_WARNING_CANONICAL,
)

EXPECTED_CSV_COLUMNS = [
    "filename",
    "brand_name",
    "class_type",
    "alcohol_content",
    "net_contents",
    "bottler_name",
    "bottler_address",
    "country_of_origin",
    "government_warning",
]

SAMPLE_CSV = """filename,brand_name,class_type,alcohol_content,net_contents,bottler_name,bottler_address,country_of_origin,government_warning
label_001.jpg,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45% Alc./Vol. (90 Proof),750 mL,Old Tom Distilling Co.,123 Distillery Lane Louisville KY 40201,,{warning}
label_002.jpg,SILVER PEAK VODKA,Vodka,40% Alc./Vol. (80 Proof),1 L,Silver Peak Spirits LLC,456 Spirits Ave Denver CO 80202,,{warning}
""".format(warning=GOVERNMENT_WARNING_CANONICAL)


def render():
    st.markdown("""
    <div class='app-header'>
        <span class='app-title'>Batch Label Review</span>
        <span class='app-badge'>BULK PROCESSING</span>
    </div>
    <div class='app-subtitle'>
        Upload multiple label images and a CSV of application data to review in bulk.
        Results are downloadable as a report.
    </div>
    """, unsafe_allow_html=True)

    # ── API Key ───────────────────────────────────────────────────────────────
    with st.expander("⚙️ API Configuration", expanded="api_key" not in st.session_state):
        api_key = st.text_input(
            "Anthropic API Key",
            type="password",
            value=st.session_state.get("api_key", ""),
            key="batch_api_key",
            placeholder="sk-ant-..."
        )
        if api_key:
            st.session_state["api_key"] = api_key
            st.success("API key saved for this session.")

    st.markdown("---")

    # ── Instructions ──────────────────────────────────────────────────────────
    with st.expander("📋 How to use batch review", expanded=False):
        st.markdown("""
        **Step 1:** Download the CSV template below and fill in your application data.
        - The `filename` column must match your uploaded image filenames exactly.
        - Leave `government_warning` blank to auto-check against the TTB canonical warning.

        **Step 2:** Upload all your label images (JPG, PNG, WebP).

        **Step 3:** Upload your completed CSV.

        **Step 4:** Click **Run Batch Review**. Results will appear in a table and can be downloaded.

        > **Tip:** For large batches (200+ labels), processing takes approximately 3–5 seconds per label.
        """)
        st.download_button(
            "⬇️ Download CSV Template",
            data=SAMPLE_CSV,
            file_name="ttb_batch_template.csv",
            mime="text/csv",
        )

    st.markdown("---")

    # ── Upload Section ────────────────────────────────────────────────────────
    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.markdown("#### 1 — Upload Label Images")
        uploaded_images = st.file_uploader(
            "Upload label images",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            label_visibility="collapsed",
            key="batch_images"
        )
        if uploaded_images:
            st.success(f"{len(uploaded_images)} image(s) uploaded")
            with st.expander("Preview uploaded images"):
                cols = st.columns(3)
                for i, img in enumerate(uploaded_images[:9]):  # preview up to 9
                    with cols[i % 3]:
                        st.image(img, caption=img.name, use_container_width=True)
                if len(uploaded_images) > 9:
                    st.caption(f"... and {len(uploaded_images) - 9} more")

    with col2:
        st.markdown("#### 2 — Upload Application CSV")
        uploaded_csv = st.file_uploader(
            "Upload CSV",
            type=["csv"],
            label_visibility="collapsed",
            key="batch_csv"
        )

        if uploaded_csv:
            try:
                df = pd.read_csv(uploaded_csv)
                st.success(f"CSV loaded: {len(df)} application(s)")
                st.dataframe(df.head(5), use_container_width=True, height=200)

                missing_cols = [c for c in ["filename", "brand_name"] if c not in df.columns]
                if missing_cols:
                    st.error(f"CSV is missing required columns: {missing_cols}")
            except Exception as e:
                st.error(f"Could not parse CSV: {e}")
                df = None
        else:
            df = None

    st.markdown("---")

    # ── Run Batch ─────────────────────────────────────────────────────────────
    run_batch = st.button("🔍 Run Batch Review", type="primary")

    if run_batch:
        if not uploaded_images:
            st.error("Please upload label images.")
            return
        if df is None or uploaded_csv is None:
            st.error("Please upload a valid CSV file.")
            return
        if not st.session_state.get("api_key"):
            st.error("Please enter your Anthropic API key.")
            return

        # Build image lookup by filename
        image_lookup = {f.name: f for f in uploaded_images}

        results_rows = []
        progress_bar = st.progress(0, text="Starting batch review...")
        status_placeholder = st.empty()

        total = len(df)
        errors = 0

        for idx, row in df.iterrows():
            filename = str(row.get("filename", "")).strip()
            progress_pct = idx / total
            progress_bar.progress(progress_pct, text=f"Processing {idx + 1}/{total}: {filename}")
            status_placeholder.caption(f"⏳ Reviewing `{filename}`...")

            if filename not in image_lookup:
                results_rows.append({
                    "filename": filename,
                    "verdict": "ERROR",
                    "brand_name": row.get("brand_name", ""),
                    "details": f"Image file '{filename}' not found in upload.",
                    "processing_ms": 0,
                })
                errors += 1
                continue

            img_file = image_lookup[filename]
            img_bytes = img_file.read()
            img_file.seek(0)  # Reset for potential re-reads

            app_data = {}
            for col in EXPECTED_CSV_COLUMNS[1:]:
                val = row.get(col, "")
                app_data[col] = str(val) if pd.notna(val) and str(val).strip() else ""

            # Auto-fill canonical warning if blank
            if not app_data.get("government_warning", "").strip():
                app_data["government_warning"] = GOVERNMENT_WARNING_CANONICAL

            try:
                result = verify_label(
                    image_bytes=img_bytes,
                    application_data=app_data,
                    api_key=st.session_state["api_key"],
                    media_type=get_media_type(filename),
                )

                # Summarize failures
                failures = [
                    f"{r.field}: {r.message}"
                    for r in result.field_results
                    if r.status == "fail"
                ]
                warnings = [
                    f"{r.field}: {r.message}"
                    for r in result.field_results
                    if r.status == "warning"
                ]

                results_rows.append({
                    "filename": filename,
                    "verdict": result.verdict,
                    "brand_name": result.raw_extracted.get("brand_name", ""),
                    "failures": "; ".join(failures) if failures else "—",
                    "warnings": "; ".join(warnings) if warnings else "—",
                    "image_notes": result.extraction_notes or "—",
                    "processing_ms": result.processing_time_ms,
                })

            except Exception as e:
                errors += 1
                results_rows.append({
                    "filename": filename,
                    "verdict": "ERROR",
                    "brand_name": row.get("brand_name", ""),
                    "failures": f"Processing error: {str(e)}",
                    "warnings": "—",
                    "image_notes": "—",
                    "processing_ms": 0,
                })

        progress_bar.progress(1.0, text="Batch complete!")
        status_placeholder.empty()

        # ── Results Table ──────────────────────────────────────────────────────
        results_df = pd.DataFrame(results_rows)

        approved = len(results_df[results_df["verdict"] == "APPROVED"])
        rejected = len(results_df[results_df["verdict"] == "REJECTED"])

        st.markdown("---")
        st.markdown("#### Batch Results Summary")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Reviewed", total)
        m2.metric("Approved", approved, delta=None)
        m3.metric("Rejected", rejected, delta=None)
        m4.metric("Errors", errors, delta=None)

        st.markdown("<br>", unsafe_allow_html=True)

        # Color-code verdict column
        def style_verdict(val):
            if val == "APPROVED":
                return "color: #065f46; font-weight: 700;"
            elif val == "REJECTED":
                return "color: #991b1b; font-weight: 700;"
            return "color: #92400e; font-weight: 700;"

        st.dataframe(
            results_df,
            use_container_width=True,
            column_config={
                "verdict": st.column_config.TextColumn("Verdict", width=100),
                "filename": st.column_config.TextColumn("File", width=160),
                "brand_name": st.column_config.TextColumn("Brand Name", width=180),
                "failures": st.column_config.TextColumn("Failed Fields", width=300),
                "warnings": st.column_config.TextColumn("Warnings", width=200),
                "processing_ms": st.column_config.NumberColumn("Time (ms)", width=90),
            }
        )

        # Download results
        csv_out = results_df.to_csv(index=False)
        st.download_button(
            "⬇️ Download Results CSV",
            data=csv_out,
            file_name="ttb_batch_results.csv",
            mime="text/csv",
            type="primary",
        )
