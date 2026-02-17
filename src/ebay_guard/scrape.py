from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def fetch_listing_text(url: str, timeout: int = 12) -> str:
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Drop scripts/styles to keep the model context cleaner.
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = _find_first_text(
        soup,
        [
            "h1.x-item-title__mainTitle span",
            "h1#itemTitle",
            "meta[property='og:title']",
            "title",
        ],
    )
    price = _find_first_text(
        soup,
        [
            "div.x-price-primary span",
            "span[itemprop='price']",
            "meta[property='product:price:amount']",
        ],
    )
    condition = _find_first_text(soup, ["div.x-item-condition-text span", "span#vi-itm-cond"])
    seller = _find_first_text(
        soup,
        [
            "div.x-sellercard-atf__info__about-seller a",
            "span.mbg-nw",
            "a[href*='feedback']",
        ],
    )
    body_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    sections = [
        f"URL: {url}",
        f"Title: {title or 'unknown'}",
        f"Price: {price or 'unknown'}",
        f"Condition: {condition or 'unknown'}",
        f"Seller: {seller or 'unknown'}",
        f"PageText: {body_text[:12000]}",
    ]
    return "\n".join(sections)


def _find_first_text(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    for selector in selectors:
        el = soup.select_one(selector)
        if not el:
            continue

        if el.name == "meta":
            val = el.get("content")
        else:
            val = el.get_text(" ", strip=True)

        if val:
            return val

    return None
