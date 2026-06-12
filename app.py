import sys
import os

# Ensure repo root is always on the path — required for Streamlit Cloud
_root = os.path.abspath(os.path.dirname(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

import streamlit as st

st.set_page_config(
    page_title="TTB Label Verifier",
    page_icon="🏷️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #0f1923;
        border-right: 1px solid #1e2d3d;
    }
    [data-testid="stSidebar"] * {
        color: #c9d8e8 !important;
    }
    [data-testid="stSidebar"] .stRadio label {
        font-size: 0.9rem;
        padding: 6px 0;
    }

    /* Main area */
    .main .block-container {
        padding-top: 2rem;
        max-width: 1100px;
    }

    /* Header */
    .app-header {
        display: flex;
        align-items: baseline;
        gap: 12px;
        margin-bottom: 0.25rem;
    }
    .app-title {
        font-size: 1.6rem;
        font-weight: 700;
        color: #0f1923;
        letter-spacing: -0.5px;
    }
    .app-badge {
        font-family: 'DM Mono', monospace;
        font-size: 0.7rem;
        background: #e8f0fe;
        color: #1a56db;
        padding: 2px 8px;
        border-radius: 3px;
        font-weight: 500;
        letter-spacing: 0.05em;
    }
    .app-subtitle {
        color: #64748b;
        font-size: 0.9rem;
        margin-bottom: 2rem;
    }

    /* Result cards */
    .result-card {
        background: #fff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
    }
    .result-pass {
        border-left: 4px solid #10b981;
    }
    .result-fail {
        border-left: 4px solid #ef4444;
    }
    .result-warn {
        border-left: 4px solid #f59e0b;
    }

    .field-label {
        font-family: 'DM Mono', monospace;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #94a3b8;
        margin-bottom: 2px;
    }
    .field-value {
        font-size: 0.95rem;
        color: #1e293b;
        font-weight: 500;
    }

    /* Verdict banner */
    .verdict-pass {
        background: #ecfdf5;
        border: 1px solid #a7f3d0;
        border-radius: 8px;
        padding: 1rem 1.5rem;
        color: #065f46;
        font-weight: 600;
        font-size: 1.1rem;
        text-align: center;
    }
    .verdict-fail {
        background: #fef2f2;
        border: 1px solid #fecaca;
        border-radius: 8px;
        padding: 1rem 1.5rem;
        color: #991b1b;
        font-weight: 600;
        font-size: 1.1rem;
        text-align: center;
    }

    /* Divider */
    hr {
        border: none;
        border-top: 1px solid #e2e8f0;
        margin: 1.5rem 0;
    }

    /* Upload area */
    [data-testid="stFileUploader"] {
        border: 2px dashed #cbd5e1;
        border-radius: 8px;
        padding: 0.5rem;
    }

    /* Batch table */
    .batch-row-pass { color: #065f46; font-weight: 600; }
    .batch-row-fail { color: #991b1b; font-weight: 600; }

    /* Spinner override */
    .stSpinner > div { border-top-color: #1a56db !important; }

    /* Input labels */
    .stTextInput label, .stTextArea label, .stSelectbox label {
        font-size: 0.85rem;
        font-weight: 500;
        color: #475569;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        background: #f8fafc;
        padding: 4px;
        border-radius: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 6px;
        font-size: 0.88rem;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

from views import single_label, batch_review, about

# Sidebar navigation
with st.sidebar:
    st.markdown("### 🏷️ TTB Label Verifier")
    st.markdown("---")
    page = st.radio(
        "Navigate",
        ["Single Label Review", "Batch Upload", "About & Documentation"],
        label_visibility="collapsed"
    )
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

# Route pages
if page == "Single Label Review":
    single_label.render()
elif page == "Batch Upload":
    batch_review.render()
elif page == "About & Documentation":
    about.render()
