# eBay Guard Agent (LangGraph + Python)

A LangGraph-based AI agent that evaluates an eBay listing for:
1. Counterfeit/authenticity risk
2. Seller reliability/trustworthiness
3. Pricing quality + timing recommendation

## What it does

The workflow has 5 nodes:
1. `ingest`: combines structured listing fields + optional scraped listing text
2. `authenticity`: scores counterfeit risk
3. `seller`: scores seller trust risk
4. `pricing`: estimates price fairness and timing action
5. `final`: combines all analysis into one recommendation

Output is strict JSON (`AgentDecision`) with risk scores, verdicts, summary, and next steps.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`.

For stronger listing extraction, also set eBay API credentials:

```bash
EBAY_CLIENT_ID=...
EBAY_CLIENT_SECRET=...
```

Install the Playwright browser once (for screenshot-based fallback extraction):

```bash
playwright install chromium
```

## Run CLI

### Option A: from structured JSON

```bash
ebay-guard analyze --data-file sample_listing.json
```

### Option B: just pass a URL

```bash
ebay-guard analyze --url "https://www.ebay.com/itm/1234567890"
```

### Option C: paste listing text

```bash
ebay-guard analyze --listing-text "Title: ... Price: ... Seller: ..."
```

## Run Web UI

```bash
streamlit run src/ebay_guard/webui.py
```

Or with the venv helper launcher:

```bash
ebay-guard-ui
```

What you get:
- URL paste + optional listing text input
- Optional structured seller/price/comparables fields
- Clear card layout for authenticity, seller, and pricing verdicts
- Overall recommendation summary and next-step checklist
- Expandable raw JSON for debugging

## Notes and limits

- This is a decision-support assistant, not a guarantee of authenticity.
- Extraction order is:
  1. eBay Browse API (if credentials configured)
  2. Screenshot + vision extraction (if core fields are still missing)
  3. HTML scraping fallback
- Some eBay pages still block scraping or hide details from non-browser clients.
- Price timing quality depends on comparable data quality. Better comparables = better recommendations.
- Browse API comparables are active listings; sold-data comps require additional eBay APIs/datasets.

## Next upgrades (recommended)

- Add a retrieval step for sold comparable listings (past 30/90 days).
- Track category-level price trends for buy-now vs wait decisions.
- Add image checks (logo placement, serial format, packaging cues).
- Add human-readable markdown report output in addition to JSON.
