from __future__ import annotations

import json
import os
from typing import Any, TypeVar, TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from .ebay_api import EbayAPIClient, parse_legacy_item_id
from .models import (
    AgentDecision,
    ComparableItem,
    ListingInput,
    PriceAssessment,
    RiskAssessment,
)
from .scrape import fetch_listing_text
from .visual_extract import capture_listing_screenshots, extract_listing_from_images

load_dotenv()


class AgentState(TypedDict, total=False):
    listing: ListingInput
    listing_context: str
    authenticity: RiskAssessment
    seller: RiskAssessment
    pricing: PriceAssessment
    decision: AgentDecision


SchemaT = TypeVar("SchemaT", bound=BaseModel)


def _llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
        temperature=0,
    )


def _coerce_structured(result: Any, schema: type[SchemaT]) -> SchemaT:
    if isinstance(result, schema):
        return result

    parsed = getattr(result, "parsed", None)
    if parsed is not None:
        if isinstance(parsed, schema):
            return parsed
        return schema.model_validate(parsed)

    if isinstance(result, dict):
        return schema.model_validate(result)

    content = getattr(result, "content", None)
    if isinstance(content, str):
        try:
            return schema.model_validate(json.loads(content))
        except Exception:  # noqa: BLE001
            pass

    return schema.model_validate(result)


def _build_context(listing: ListingInput) -> str:
    listing_for_analysis, api_context = _enrich_listing_with_ebay_api(listing)
    listing_for_analysis, vision_context = _enrich_listing_with_vision(listing_for_analysis)
    fields_blob = listing_for_analysis.model_dump(mode="json")
    manual_data = json.dumps(fields_blob, indent=2)

    scraped_text = ""
    if listing_for_analysis.listing_url:
        try:
            scraped_text = fetch_listing_text(listing_for_analysis.listing_url)
        except Exception as exc:  # noqa: BLE001
            scraped_text = f"Failed to fetch URL: {exc}"

    return (
        "Structured Listing Data:\n"
        f"{manual_data}\n\n"
        "eBay API Context:\n"
        f"{api_context}\n\n"
        "Vision Context:\n"
        f"{vision_context}\n\n"
        "Scraped URL Context:\n"
        f"{scraped_text}\n"
    )


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _enrich_listing_with_ebay_api(listing: ListingInput) -> tuple[ListingInput, str]:
    client = EbayAPIClient.from_env()
    if not client.is_configured:
        return listing, "Skipped: EBAY_CLIENT_ID/EBAY_CLIENT_SECRET not set."

    if not listing.listing_url:
        return listing, "Skipped: no listing_url was provided."

    legacy_item_id = parse_legacy_item_id(listing.listing_url)
    if not legacy_item_id:
        return listing, "Skipped: could not parse legacy item id from URL."

    try:
        item = client.get_item_by_legacy_id(legacy_item_id)
    except Exception as exc:  # noqa: BLE001
        return listing, f"Failed to fetch eBay item via API: {exc}"

    enriched = listing.model_copy(deep=True)

    if not enriched.listing_title:
        enriched.listing_title = item.get("title")

    if enriched.listing_price is None:
        enriched.listing_price = _safe_float(item.get("price", {}).get("value"))

    if not enriched.listing_condition:
        enriched.listing_condition = item.get("condition")

    seller = item.get("seller", {})
    if not enriched.seller_name:
        enriched.seller_name = seller.get("username")

    if enriched.seller_feedback_percent is None:
        enriched.seller_feedback_percent = _safe_float(seller.get("feedbackPercentage"))

    if enriched.seller_feedback_count is None:
        feedback_score = _safe_float(seller.get("feedbackScore"))
        if feedback_score is not None:
            enriched.seller_feedback_count = int(feedback_score)

    if not enriched.return_policy:
        policy = item.get("returnTerms", {})
        policy_summary = policy.get("returnsAccepted")
        window = policy.get("returnPeriod", {}).get("value")
        if policy_summary is not None and window is not None:
            enriched.return_policy = f"returnsAccepted={policy_summary}, returnWindowDays={window}"
        elif policy_summary is not None:
            enriched.return_policy = f"returnsAccepted={policy_summary}"

    comparables_added = 0
    if not enriched.comparables and (enriched.listing_title or item.get("title")):
        query = (enriched.listing_title or item.get("title") or "").strip()
        category_ids = item.get("leafCategoryIds") or []
        try:
            summaries = client.search_similar_items(query=query, category_ids=category_ids, limit=12)
        except Exception:  # noqa: BLE001
            summaries = []

        for summary in summaries:
            if summary.get("legacyItemId") == legacy_item_id:
                continue

            title = summary.get("title")
            price = _safe_float(summary.get("price", {}).get("value"))
            if not title or price is None:
                continue

            enriched.comparables.append(
                ComparableItem(
                    title=title,
                    price=price,
                    condition=summary.get("condition"),
                    source="eBay Browse API",
                )
            )
            comparables_added += 1
            if comparables_added >= 10:
                break

    api_context = json.dumps(
        {
            "api_source": "eBay Browse API",
            "legacy_item_id": legacy_item_id,
            "item_title": item.get("title"),
            "item_web_url": item.get("itemWebUrl"),
            "item_location": item.get("itemLocation"),
            "seller": item.get("seller"),
            "condition": item.get("condition"),
            "price": item.get("price"),
            "estimated_availability_status": item.get("estimatedAvailabilities"),
            "returns": item.get("returnTerms"),
            "category_path": item.get("categoryPath"),
            "comparables_added": comparables_added,
        },
        indent=2,
    )
    return enriched, api_context


def _enrich_listing_with_vision(listing: ListingInput) -> tuple[ListingInput, str]:
    if not listing.listing_url:
        return listing, "Skipped: no listing_url was provided."

    missing_core_fields = (
        not listing.listing_title
        or listing.listing_price is None
        or not listing.seller_name
        or not listing.listing_condition
    )

    if not missing_core_fields:
        return listing, "Skipped: core listing fields already populated."

    screenshot_paths, screenshot_status = capture_listing_screenshots(listing.listing_url)
    if not screenshot_paths:
        return listing, screenshot_status

    extracted, extraction_status = extract_listing_from_images(
        image_paths=screenshot_paths,
        listing_url=listing.listing_url,
    )
    if extracted is None:
        return listing, f"{screenshot_status} {extraction_status}"

    enriched = listing.model_copy(deep=True)
    if not enriched.listing_title and extracted.listing_title:
        enriched.listing_title = extracted.listing_title
    if enriched.listing_price is None and extracted.listing_price is not None:
        enriched.listing_price = extracted.listing_price
    if not enriched.listing_condition and extracted.listing_condition:
        enriched.listing_condition = extracted.listing_condition
    if not enriched.seller_name and extracted.seller_name:
        enriched.seller_name = extracted.seller_name
    if not enriched.return_policy and extracted.return_policy:
        enriched.return_policy = extracted.return_policy

    vision_context = json.dumps(
        {
            "status": f"{screenshot_status} {extraction_status}",
            "confidence": extracted.confidence,
            "evidence": extracted.evidence,
            "caveats": extracted.caveats,
            "screenshots": [str(p) for p in screenshot_paths],
        },
        indent=2,
    )
    return enriched, vision_context


def ingest_listing_node(state: AgentState) -> AgentState:
    listing = state["listing"]
    return {"listing_context": _build_context(listing)}


def authenticity_node(state: AgentState) -> AgentState:
    parser_llm = _llm().with_structured_output(RiskAssessment)
    prompt = f"""
You are an e-commerce fraud analyst.
Evaluate counterfeiting/authenticity risk for this eBay listing.

Return a RiskAssessment with:
- score: 0-100 where 100 = very high counterfeit risk
- verdict: low, medium, or high
- reasons: concrete evidence-based reasons
- red_flags: suspicious signals
- confidence: 0-1

Important:
- Be conservative when data is missing.
- Do not claim certainty from weak signals.

Listing data:
{state['listing_context']}
""".strip()

    authenticity = _coerce_structured(parser_llm.invoke(prompt), RiskAssessment)
    return {"authenticity": authenticity}


def seller_node(state: AgentState) -> AgentState:
    parser_llm = _llm().with_structured_output(RiskAssessment)
    prompt = f"""
You are a marketplace trust and safety analyst.
Evaluate seller reliability/trustworthiness for this listing.

Return a RiskAssessment with:
- score: 0-100 where 100 = very high seller risk
- verdict: low, medium, or high
- reasons: concrete reasons
- red_flags: suspicious account behavior or policy risk
- confidence: 0-1

Focus on:
- feedback %, feedback count, account age
- return policy clarity
- listing quality consistency
- inconsistencies that indicate scam risk

Listing data:
{state['listing_context']}
""".strip()

    seller = _coerce_structured(parser_llm.invoke(prompt), RiskAssessment)
    return {"seller": seller}


def pricing_node(state: AgentState) -> AgentState:
    parser_llm = _llm().with_structured_output(PriceAssessment)
    prompt = f"""
You are a pricing analyst for collectible and consumer goods listings.
Assess whether this listing price is good, fair, or overpriced.

Return PriceAssessment with:
- score: 0-100 where 100 = very overpriced risk
- verdict: undervalued, fair, overpriced, or insufficient_data
- suggested_action: buy_now, make_offer, wait, compare_more
- expected_fair_range_low/high: numeric estimates when possible
- reasons: include trend/timing logic if inferable
- confidence: 0-1

Rules:
- Use comparables if provided.
- If not enough reliable pricing data exists, choose insufficient_data and compare_more.
- Do not fabricate market prices.

Listing data:
{state['listing_context']}
""".strip()

    pricing = _coerce_structured(parser_llm.invoke(prompt), PriceAssessment)
    return {"pricing": pricing}


def final_decision_node(state: AgentState) -> AgentState:
    parser_llm = _llm().with_structured_output(AgentDecision)
    prompt = f"""
You are a final purchase decision assistant.
Combine the three analyses below into one actionable decision.

Authenticity analysis:
{state['authenticity'].model_dump_json(indent=2)}

Seller analysis:
{state['seller'].model_dump_json(indent=2)}

Pricing analysis:
{state['pricing'].model_dump_json(indent=2)}

Output AgentDecision with:
- overall_recommendation: buy | buy_with_caution | skip | wait | needs_more_data
- summary: 2-4 sentences
- next_steps: concise practical checklist

Keep recommendations risk-aware and realistic.
""".strip()

    decision = _coerce_structured(parser_llm.invoke(prompt), AgentDecision)
    return {"decision": decision}


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("ingest", ingest_listing_node)
    graph.add_node("authenticity", authenticity_node)
    graph.add_node("seller", seller_node)
    graph.add_node("pricing", pricing_node)
    graph.add_node("final", final_decision_node)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "authenticity")
    graph.add_edge("authenticity", "seller")
    graph.add_edge("seller", "pricing")
    graph.add_edge("pricing", "final")
    graph.add_edge("final", END)
    return graph.compile()


graph = build_graph()


def run_agent(listing: ListingInput) -> AgentDecision:
    result = graph.invoke({"listing": listing})
    return result["decision"]
