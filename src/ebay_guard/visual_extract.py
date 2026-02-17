from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from .models import VisualListingExtraction


def _to_data_url(path: Path) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def capture_listing_screenshots(url: str) -> tuple[list[Path], str]:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        return [], "Skipped: Playwright is not installed."

    screenshot_paths: list[Path] = []
    out_dir = Path(tempfile.mkdtemp(prefix="ebay_guard_"))

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 2200},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1200)

            full_page = out_dir / "listing_full.png"
            page.screenshot(path=str(full_page), full_page=True)
            screenshot_paths.append(full_page)

            clip_main = out_dir / "listing_top.png"
            page.screenshot(path=str(clip_main), clip={"x": 0, "y": 0, "width": 1440, "height": 1100})
            screenshot_paths.append(clip_main)

            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(700)

            clip_mid = out_dir / "listing_mid.png"
            page.screenshot(path=str(clip_mid), clip={"x": 0, "y": 700, "width": 1440, "height": 1200})
            screenshot_paths.append(clip_mid)

            context.close()
            browser.close()
    except Exception as exc:  # noqa: BLE001
        return [], f"Failed to capture screenshots: {exc}"

    return screenshot_paths, f"Captured {len(screenshot_paths)} screenshots with Playwright."


def extract_listing_from_images(
    image_paths: list[Path],
    listing_url: str,
) -> tuple[VisualListingExtraction | None, str]:
    if not image_paths:
        return None, "Skipped: no screenshots available."

    model = os.getenv("OPENAI_VISION_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1"))
    llm = ChatOpenAI(model=model, temperature=0).with_structured_output(VisualListingExtraction)

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "Extract listing fields from these eBay screenshots. "
                "Only return values that are clearly visible. "
                "If uncertain, leave the field null and mention why in caveats. "
                "Treat price as numeric without currency symbols."
            ),
        },
        {"type": "text", "text": f"Listing URL: {listing_url}"},
    ]

    for path in image_paths:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": _to_data_url(path)},
            }
        )

    try:
        result = llm.invoke([HumanMessage(content=content)])
    except Exception as exc:  # noqa: BLE001
        return None, f"Vision extraction failed: {exc}"

    if isinstance(result, VisualListingExtraction):
        return result, "Vision extraction succeeded."

    parsed = getattr(result, "parsed", None)
    if isinstance(parsed, VisualListingExtraction):
        return parsed, "Vision extraction succeeded (parsed wrapper)."

    try:
        if parsed is not None:
            return VisualListingExtraction.model_validate(parsed), "Vision extraction succeeded (validated parsed)."

        if isinstance(result, dict):
            return VisualListingExtraction.model_validate(result), "Vision extraction succeeded (validated dict)."

        content_text = getattr(result, "content", None)
        if isinstance(content_text, str):
            return (
                VisualListingExtraction.model_validate(json.loads(content_text)),
                "Vision extraction succeeded (validated JSON content).",
            )
    except Exception as exc:  # noqa: BLE001
        return None, f"Vision output parse failed: {exc}"

    return None, "Vision extraction returned an unsupported payload shape."
