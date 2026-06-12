"""
About & Documentation page.
Explains approach, tools, assumptions, and trade-offs.
"""

import streamlit as st
from utils.analyzer import GOVERNMENT_WARNING_CANONICAL


def render():
    st.markdown("""
    <div class='app-header'>
        <span class='app-title'>About This Tool</span>
        <span class='app-badge'>DOCUMENTATION</span>
    </div>
    <div class='app-subtitle'>
        Approach, technical decisions, and known limitations.
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    ## What This Tool Does

    The TTB Label Verifier is an AI-powered prototype that automates the first-pass compliance check
    for Alcohol and Tobacco Tax and Trade Bureau (TTB) Certificate of Label Approval (COLA) applications.

    An agent uploads a label image and enters the corresponding COLA application data.
    The tool uses a large language model with vision capability to extract every field from the label,
    then compares each field against the application values and flags mismatches.

    ---

    ## Architecture

    ```
    Label Image + Application Fields
            │
            ▼
    Claude claude-sonnet-4-6 (Vision)
    ── Extracts all text fields from image
    ── Returns structured JSON
            │
            ▼
    Field Comparison Engine
    ── Government Warning: strict exact-match
    ── All other fields: fuzzy normalized match
    ── Partial match → WARNING (human review)
    ── Full mismatch → FAIL
            │
            ▼
    Per-field results + Overall Verdict
    (APPROVED / REJECTED)
    ```

    ---

    ## Technical Choices

    | Decision | Choice | Rationale |
    |---|---|---|
    | AI model | Claude claude-sonnet-4-6 vs. OCR + regex | LLM vision handles curved bottle surfaces, glare, varied fonts, and layout changes without rule engineering. OCR requires clean scans and brittle regex patterns per label design. For a prototype with diverse real-world inputs, LLM wins on robustness. |
    | AI model tier | Sonnet over Opus | Sonnet hits the <5s response target; Opus is marginally more accurate but averages 7–9s — unusable per stakeholder feedback. Speed constraint drives model selection. |
    | Framework | Streamlit over Flask/FastAPI | Compliance agents are the end users, not developers. Streamlit delivers a fully interactive UI with no frontend code and deploys in minutes. Flask/FastAPI would require a separate frontend layer — appropriate for production, unnecessary for a prototype. |
    | Deployment | Streamlit Community Cloud | Zero infrastructure, public URL, free — right-sized for a proof-of-concept. Production would move to Azure Government. |
    | Matching | Fuzzy normalize for most fields; strict for government warning | Per-field strategy, not one-size-fits-all. Fuzzy handles legitimate formatting variation (Dave's case). Strict enforces a legal requirement verbatim (Jenny's case). |
    | Local model vs. API | Cloud API | A locally-hosted model would resolve the network/firewall concern but requires GPU infrastructure unavailable in this prototype context. Documented as a future option via Azure AI Services. |
    | Batch processing | Sequential with progress bar | Simple, transparent, and debuggable. Parallel async processing would reduce total batch time but adds error-handling complexity and is a clear future enhancement rather than a prototype requirement. |

    ---

    ## Beverage Type Handling

    TTB label requirements vary by beverage type. The fields verified by this tool are the
    **common mandatory elements** that apply across distilled spirits, wine, and beer:

    | Field | Distilled Spirits | Wine | Beer |
    |---|---|---|---|
    | Brand name | Required | Required | Required |
    | Class/type designation | Required | Required | Required |
    | Alcohol content (ABV) | Required | Required for wines >14% | Not always required |
    | Net contents | Required | Required | Required |
    | Bottler/producer name & address | Required | Required | Required |
    | Country of origin | Required (imports) | Required (imports) | Required (imports) |
    | Government Health Warning | Required | Required | Required |

    The current prototype applies identical field validation regardless of beverage type.
    For a production tool, validation rules would branch by type — for example, skipping
    ABV enforcement for certain beer categories where TTB does not require it. This is
    documented as a future enhancement; the prototype errs toward checking all fields
    and surfaces a WARNING rather than auto-rejecting on ambiguous cases.

    *Field requirements sourced from TTB guidelines at [ttb.gov](https://www.ttb.gov/labeling).*

    ---

    ## Field Validation Logic

    ### Government Warning (Strict)
    Per TTB regulation and agent feedback, the government warning statement must:
    - Begin with **`GOVERNMENT WARNING:`** in ALL CAPS
    - Match the canonical TTB-required text exactly (normalized whitespace)

    **Canonical required text:**
    """)

    st.code(GOVERNMENT_WARNING_CANONICAL, language=None)

    st.markdown("""
    ### All Other Fields (Fuzzy Match)
    Fields like brand name are normalized before comparison:
    - Lowercased
    - Whitespace collapsed
    - Smart quotes normalized to straight quotes

    This handles the common case where an application records `Stone's Throw` and a label prints
    `STONE'S THROW` — a clear match that should not trigger a rejection.

    A **partial match** (where one value contains the other) produces a `WARNING` status,
    flagging the field for human review without automatic rejection. This reflects feedback from
    experienced agents: not every discrepancy is a violation, and the tool should support agent
    judgment rather than replace it.

    ### Font Size and Visual Burial
    A common compliance evasion tactic is printing the government warning in an unusually small
    font, with non-standard wording, or visually buried among other label elements. Claude's
    vision model reads the full label image at pixel level — it will extract warning text
    regardless of placement or font size. If the warning is present but non-standard in wording,
    the strict text comparison will catch it. If it is too small for the model to read reliably,
    the `extraction_notes` field will flag the image quality issue for agent review.

    ---

    ## Network & Security Considerations

    This prototype calls the Anthropic API (`api.anthropic.com`) directly from the application
    server. In federal network environments where outbound traffic to external ML endpoints is
    restricted — a real and documented risk based on previous pilot experience — this call would
    fail silently or time out.

    **Production path to resolve this:**

    ```
    Agent Browser
          │
          ▼
    Azure API Management Gateway
    (inside Treasury's Azure Government boundary)
          │
          ▼
    Anthropic API via approved egress
    — or —
    Azure AI Services (Anthropic models on Azure Marketplace,
    fully within the FedRAMP-authorized Azure Government boundary)
    ```

    Treasury's existing Azure infrastructure (migrated 2019) is the natural home for this
    integration. Routing API calls through Azure API Management keeps all traffic within the
    government network perimeter, satisfies FedRAMP boundary requirements, and eliminates the
    firewall dependency that caused problems in the previous scanning vendor pilot.

    For this prototype, the API key is entered by the user at runtime and held in session memory
    only — it is never logged, stored, or transmitted beyond the Anthropic API call.

    ---

    ## Assumptions & Trade-offs

    - **No COLA integration:** This is a standalone proof-of-concept. It does not connect to the
      existing COLA (.NET) system. Field data must be entered manually or via CSV. A production
      version would integrate directly with COLA's data layer to eliminate manual entry entirely.

    - **Image quality:** Claude handles most real-world label photos including moderate angles,
      glare, and low lighting. Severely degraded images return an `extraction_notes` flag
      prompting the agent to request a better image — consistent with current workflow.

    - **No data retention:** Label images and extracted data are processed in memory only.
      Nothing is stored, logged, or persisted between sessions. Document retention policies
      for a production deployment would need to be defined with the IT and legal teams.

    - **Sequential batch processing:** Large batches (200+ labels) are processed one at a time
      with a live progress indicator. Parallel processing would reduce total time but adds
      complexity and error-handling surface area outside this prototype's scope.

    - **Agent judgment preserved:** The tool flags mismatches and warnings — it does not make
      final determinations. Every result is a recommendation to the reviewing agent, not an
      automated approval or rejection. This is intentional: experienced agents have context
      the AI does not.

    - **Country of origin:** Only validated when provided in the application. Omission is
      valid for domestic products.

    - **Net contents / ABV formatting:** Fuzzy match handles minor formatting differences
      (e.g., `750ml` vs `750 mL`). Numeric unit equivalence (e.g., `0.75 L` vs `750 mL`)
      is not currently evaluated — flagged for future work.

    ---

    ## Stakeholder Requirements Traceability

    | Requirement | Source | Status | Implementation |
    |---|---|---|---|
    | Results in < 5 seconds | Sarah Chen | ✅ | Claude claude-sonnet-4-6, avg 2–4s |
    | Batch upload for large importers | Sarah Chen / Janet (Seattle) | ✅ | Batch page: multi-image + CSV |
    | UI simple enough for non-technical users | Sarah Chen | ✅ | Streamlit, minimal chrome, plain labels |
    | Case-insensitive / fuzzy field matching | Dave Morrison | ✅ | Normalize-then-compare on all non-warning fields |
    | Agent judgment preserved, not replaced | Dave Morrison | ✅ | WARNING status routes to human review; no auto-reject on partials |
    | Exact government warning text enforcement | Jenny Park | ✅ | Strict all-caps prefix + canonical TTB text match |
    | Detection of font-size / buried warning evasion | Jenny Park | ✅ | Vision model reads full image; strict text comparison catches wording variants |
    | Imperfect / angled image handling | Jenny Park | ✅ | Claude vision + extraction_notes flag |
    | Standalone prototype, no COLA integration | Marcus Williams | ✅ | No external system dependencies |
    | No sensitive data stored | Marcus Williams | ✅ | In-memory only, no logging |
    | Network/firewall compatibility | Marcus Williams | ⚠️ | Prototype calls Anthropic API directly; production path via Azure APIM documented above |

    ---

    ## Error Handling

    The app is designed to fail gracefully at every layer:

    - **API timeout / network failure:** Caught by try/except in both the single and batch
      review pages. The user sees a plain-language error message and is prompted to retry.
      No partial results are shown — a label is either fully analyzed or flagged as errored.

    - **Malformed AI response:** If Claude returns JSON that cannot be parsed (rare but possible),
      the exception is caught, logged to the error message, and the label is marked as errored
      rather than silently approved or rejected.

    - **Unreadable image:** Claude returns an `extraction_notes` field describing any legibility
      issues. If no fields can be extracted, all fields return `null` and the label is rejected
      with an explanation, consistent with current agent workflow (request a better image).

    - **Missing CSV columns in batch mode:** The batch page validates that required columns
      (`filename`, `brand_name`) are present before processing begins.

    - **File not found in batch:** If a CSV row references a filename not present in the image
      upload, that row is marked `ERROR` with a clear message and processing continues for
      the remaining labels.

    ---

    ## Future Enhancements

    1. **Azure APIM routing** — Move API calls inside the Treasury network boundary for
       production deployment
    2. **COLA system integration** — Pull application data directly from COLA to eliminate
       manual field entry
    3. **Parallel batch processing** — Process multiple labels concurrently for high-volume queues
    4. **Confidence scoring** — Surface per-field extraction confidence so agents can prioritize
       manual review on low-confidence results
    5. **Audit log** — Track review decisions and outcomes for compliance recordkeeping
    6. **Numeric unit equivalence** — Detect that `0.75 L` and `750 mL` represent the same
       net contents

    ---

    ## About the Developer

    Built by Quinton Campbell as part of the Department of the Treasury IT Specialist (AI) GS-15
    take-home assessment. Questions: [take-home-test@treasury.gov](mailto:take-home-test@treasury.gov)
    """, unsafe_allow_html=True)
