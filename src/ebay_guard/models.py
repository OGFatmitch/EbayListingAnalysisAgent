from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ComparableItem(BaseModel):
    title: str
    price: float
    condition: str | None = None
    sold_date: str | None = None
    source: str | None = None


class ListingInput(BaseModel):
    listing_url: str | None = None
    listing_text: str | None = None
    listing_title: str | None = None
    listing_price: float | None = None
    listing_condition: str | None = None
    seller_name: str | None = None
    seller_feedback_percent: float | None = None
    seller_feedback_count: int | None = None
    seller_account_age_years: float | None = None
    return_policy: str | None = None
    comparables: list[ComparableItem] = Field(default_factory=list)


class VisualListingExtraction(BaseModel):
    listing_title: str | None = None
    listing_price: float | None = None
    listing_condition: str | None = None
    seller_name: str | None = None
    return_policy: str | None = None
    evidence: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class RiskAssessment(BaseModel):
    score: int = Field(ge=0, le=100)
    verdict: Literal["low", "medium", "high"]
    reasons: list[str]
    red_flags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class PriceAssessment(BaseModel):
    score: int = Field(ge=0, le=100)
    verdict: Literal["undervalued", "fair", "overpriced", "insufficient_data"]
    suggested_action: Literal["buy_now", "make_offer", "wait", "compare_more"]
    expected_fair_range_low: float | None = None
    expected_fair_range_high: float | None = None
    reasons: list[str]
    confidence: float = Field(ge=0, le=1)


class AgentDecision(BaseModel):
    authenticity: RiskAssessment
    seller: RiskAssessment
    pricing: PriceAssessment
    overall_recommendation: Literal[
        "buy", "buy_with_caution", "skip", "wait", "needs_more_data"
    ]
    summary: str
    next_steps: list[str]
