from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from .graph import run_agent
from .models import ListingInput

app = typer.Typer(add_completion=False)
console = Console()


@app.callback()
def main() -> None:
    """eBay Guard CLI."""


@app.command()
def analyze(
    url: str | None = typer.Option(None, help="eBay listing URL"),
    data_file: Path | None = typer.Option(
        None,
        help="Path to JSON file matching ListingInput schema",
    ),
    listing_text: str | None = typer.Option(
        None,
        help="Paste listing text when no URL is provided",
    ),
):
    payload: dict = {}

    if data_file:
        payload = json.loads(data_file.read_text())

    if url:
        payload["listing_url"] = url

    if listing_text:
        payload["listing_text"] = listing_text

    listing = ListingInput.model_validate(payload)
    decision = run_agent(listing)

    console.print_json(decision.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
