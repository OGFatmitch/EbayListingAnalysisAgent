from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ebay_guard.graph import run_agent
from ebay_guard.models import ComparableItem, ListingInput


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&display=swap');

        :root {
          --bg-start: #f4f7ec;
          --bg-end: #dfe8c8;
          --panel: #ffffff;
          --text: #1b2414;
          --muted: #55614b;
          --good: #1b8f4d;
          --warn: #c57d17;
          --bad: #bc3f35;
        }

        .stApp {
          background: radial-gradient(circle at 10% 10%, #ffffff 0%, var(--bg-start) 45%, var(--bg-end) 100%);
          color: var(--text);
          font-family: 'Space Grotesk', sans-serif;
        }

        .hero {
          background: linear-gradient(135deg, #ffffff 0%, #eef3dd 100%);
          border: 1px solid #dae4c0;
          border-radius: 18px;
          padding: 22px;
          margin-bottom: 16px;
          box-shadow: 0 8px 22px rgba(37, 56, 20, 0.08);
        }

        .hero h1 {
          margin: 0;
          font-size: 2rem;
        }

        .card {
          background: var(--panel);
          border: 1px solid #dde6c8;
          border-radius: 14px;
          padding: 16px;
          box-shadow: 0 6px 18px rgba(37, 56, 20, 0.08);
          min-height: 220px;
        }

        .label {
          font-size: 0.76rem;
          color: var(--muted);
          letter-spacing: 0.04em;
          text-transform: uppercase;
          margin-bottom: 6px;
        }

        .value {
          font-size: 1.75rem;
          font-weight: 700;
          margin-bottom: 8px;
        }

        .pill {
          display: inline-block;
          padding: 4px 10px;
          border-radius: 999px;
          font-size: 0.8rem;
          font-weight: 600;
          margin-bottom: 10px;
        }

        .pill.good { background: #dff5e9; color: var(--good); }
        .pill.warn { background: #fff2db; color: var(--warn); }
        .pill.bad { background: #ffe6e2; color: var(--bad); }

        .summary {
          background: #ffffffd6;
          border-left: 6px solid #6c8b36;
          border-radius: 12px;
          padding: 14px 16px;
          margin-top: 12px;
          margin-bottom: 12px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _badge_class(level: str) -> str:
    if level in {"low", "undervalued", "buy_now", "buy"}:
        return "good"
    if level in {"medium", "fair", "make_offer", "buy_with_caution", "wait"}:
        return "warn"
    return "bad"


def _parse_comparables(raw: str) -> list[ComparableItem]:
    if not raw.strip():
        return []

    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Comparables JSON must be a list of objects")
    return [ComparableItem.model_validate(item) for item in data]


def _result_card(title: str, score: int, verdict: str, reasons: list[str]) -> None:
    badge = _badge_class(verdict)
    reasons_html = "".join(f"<li>{r}</li>" for r in reasons[:4])
    st.markdown(
        f"""
        <div class="card">
          <div class="label">{title}</div>
          <div class="value">{score}/100</div>
          <span class="pill {badge}">{verdict}</span>
          <ul>{reasons_html}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="eBay Guard", page_icon="🛡️", layout="wide")
    _inject_styles()

    st.markdown(
        """
        <div class="hero">
          <h1>eBay Guard</h1>
          <p>Paste a listing URL and get a clear call on authenticity risk, seller trust, and price timing.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("analyze-form", clear_on_submit=False):
        url = st.text_input("eBay Listing URL", placeholder="https://www.ebay.com/itm/...")
        listing_text = st.text_area(
            "Optional listing text",
            placeholder="Paste listing details if the page blocks scraping.",
            height=120,
        )

        with st.expander("Optional structured fields"):
            col1, col2, col3 = st.columns(3)
            with col1:
                listing_title = st.text_input("Title")
                listing_price = st.number_input("Price", min_value=0.0, value=0.0, step=1.0)
            with col2:
                seller_feedback_percent = st.number_input(
                    "Seller feedback %",
                    min_value=0.0,
                    max_value=100.0,
                    value=0.0,
                    step=0.1,
                )
                seller_feedback_count = st.number_input(
                    "Feedback count",
                    min_value=0,
                    value=0,
                    step=1,
                )
            with col3:
                seller_name = st.text_input("Seller name")
                seller_account_age_years = st.number_input(
                    "Seller age (years)", min_value=0.0, value=0.0, step=0.1
                )

            return_policy = st.text_input("Return policy")
            comparables_raw = st.text_area(
                "Comparables JSON (optional)",
                placeholder='[{"title":"Item","price":149.99,"condition":"New","sold_date":"2026-02-01"}]',
                height=110,
            )

        run = st.form_submit_button("Analyze Listing", use_container_width=True)

    if run:
        try:
            comparables = _parse_comparables(comparables_raw)
            payload: dict = {
                "listing_url": url or None,
                "listing_text": listing_text or None,
                "listing_title": listing_title or None,
                "seller_name": seller_name or None,
                "return_policy": return_policy or None,
                "comparables": [item.model_dump() for item in comparables],
            }

            if listing_price > 0:
                payload["listing_price"] = listing_price
            if seller_feedback_percent > 0:
                payload["seller_feedback_percent"] = seller_feedback_percent
            if seller_feedback_count > 0:
                payload["seller_feedback_count"] = int(seller_feedback_count)
            if seller_account_age_years > 0:
                payload["seller_account_age_years"] = seller_account_age_years

            listing = ListingInput.model_validate(payload)
            with st.spinner("Running analysis..."):
                st.session_state["decision"] = run_agent(listing)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to analyze listing: {exc}")

    decision = st.session_state.get("decision")
    if not decision:
        return

    rec_badge = _badge_class(decision.overall_recommendation)
    st.markdown(
        f"""
        <div class="summary">
          <div class="label">Overall Recommendation</div>
          <span class="pill {rec_badge}">{decision.overall_recommendation}</span>
          <p>{decision.summary}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        _result_card(
            "Authenticity Risk",
            decision.authenticity.score,
            decision.authenticity.verdict,
            decision.authenticity.reasons,
        )
    with c2:
        _result_card(
            "Seller Trust Risk",
            decision.seller.score,
            decision.seller.verdict,
            decision.seller.reasons,
        )
    with c3:
        _result_card(
            "Pricing Signal",
            decision.pricing.score,
            decision.pricing.verdict,
            decision.pricing.reasons,
        )

    st.subheader("Recommended Next Steps")
    for step in decision.next_steps:
        st.write(f"- {step}")

    with st.expander("Raw JSON"):
        st.json(decision.model_dump())


if __name__ == "__main__":
    main()
