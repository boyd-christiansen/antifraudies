"""Command-line interface.

    antifraudies enumerate --vendor thermofisher --limit 50
    antifraudies scrape --vendor thermofisher --seed seeds/thermofisher_seed.txt
    antifraudies scrape --vendor thermofisher --limit 100          # from sitemap
    antifraudies report                                            # cross-image queries
"""

from __future__ import annotations

from pathlib import Path

import typer

from .adapters import ADAPTERS
from .config import get_settings
from .crawl.http import PoliteClient
from .crawl.robots import RobotsPolicy
from .scrape import ScrapeOrchestrator, iter_seed_file
from .store.db import Database

app = typer.Typer(
    add_completion=False,
    help="Catalog-scale forensic image-provenance scraper. Surfaces evidence for human "
    "review; never renders a verdict.",
)


def _build(vendor: str, concurrency: int | None = None):
    if vendor not in ADAPTERS:
        raise typer.BadParameter(f"unknown vendor '{vendor}'. Known: {', '.join(ADAPTERS)}")
    settings = get_settings()
    if concurrency is not None:
        settings.crawl.concurrency = concurrency
    settings.ensure_dirs()
    client = PoliteClient(settings)
    robots = RobotsPolicy(client, settings.crawl.user_agent) if settings.crawl.respect_robots else None
    adapter = ADAPTERS[vendor](client, robots)
    db = Database(settings.db_path)
    return settings, client, adapter, db


@app.command()
def enumerate(
    vendor: str = typer.Option("thermofisher", "--vendor", "-v"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max product URLs to list."),
) -> None:
    """List product URLs from the vendor's robots-allowed sitemaps (no pages fetched)."""
    _settings, client, adapter, db = _build(vendor)
    try:
        for ref in adapter.enumerate(limit=limit):
            typer.echo(f"{ref.catalog_number}\t{ref.product_url}")
    finally:
        client.close()
        db.close()


@app.command()
def scrape(
    vendor: str = typer.Option("thermofisher", "--vendor", "-v"),
    seed: Path = typer.Option(None, "--seed", help="Seed file: one URL or catalog number per line."),
    limit: int = typer.Option(None, "--limit", "-n", help="Cap products when crawling the sitemap."),
    concurrency: int = typer.Option(None, "--concurrency", "-c", help="Max requests in flight (overrides config)."),
    no_images: bool = typer.Option(False, "--no-images", help="Record metadata but skip image bytes."),
) -> None:
    """Scrape products: fetch pages concurrently, store image bytes + metadata rows."""
    settings, client, adapter, db = _build(vendor, concurrency=concurrency)
    try:
        if seed is not None:
            refs = adapter.seed(iter_seed_file(seed))
        else:
            refs = adapter.enumerate(limit=limit)
        orch = ScrapeOrchestrator(settings, client, adapter, db)
        summary = orch.run(refs, download_images=not no_images)
    finally:
        client.close()
        db.close()

    typer.echo(f"products:            {summary.products}")
    typer.echo(f"images:              {summary.images}")
    typer.echo(f"image bytes captured:{summary.image_bytes_captured}")
    typer.echo("provenance:")
    for prov, n in sorted(summary.provenance_counts.items()):
        typer.echo(f"  {prov:38s} {n}")
    if summary.errors:
        typer.echo(f"errors ({len(summary.errors)}):")
        for e in summary.errors[:20]:
            typer.echo(f"  {e}")


@app.command()
def report(vendor: str = typer.Option("thermofisher", "--vendor", "-v")) -> None:
    """Demonstrate cross-image queries over the stored corpus (a phase-2 preview)."""
    _settings, client, _adapter, db = _build(vendor)
    try:
        typer.echo(f"total images:        {db.count_images()}")
        for prov in (
            "internal_testing_data",
            "internal_advanced_verification",
            "third_party_published_figure",
        ):
            typer.echo(f"  {prov:38s} {db.count_images(prov)}")

        typer.echo("\nprovenance x rendered modality (which forensics apply):")
        for row in db.modality_matrix():
            typer.echo(f"  {row['provenance']:32s} {str(row['modality']):16s} {row['n']}")

        shared = db.images_sharing_content()
        typer.echo(f"\nimages reused across products (same content hash): {len(shared)}")
        for row in shared[:20]:
            typer.echo(f"  {row['content_sha256'][:12]}  {row['n_products']} products: {row['products']}")

        ts = db.images_sharing_timestamp(internal_only=True)
        typer.echo(f"\ninternal images sharing a filename timestamp: {len(ts)}")
        for row in ts[:20]:
            typer.echo(f"  {row['fn_timestamp']}  {row['n_products']} products / {row['n_images']} images")
    finally:
        client.close()
        db.close()


if __name__ == "__main__":
    app()
