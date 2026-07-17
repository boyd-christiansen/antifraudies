"""Command-line interface.

    antifraudies enumerate --vendor thermofisher --limit 50
    antifraudies scrape --vendor thermofisher --seed seeds/thermofisher_seed.txt
    antifraudies scrape --vendor thermofisher --limit 100          # from sitemap
    antifraudies report                                            # cross-image queries
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from .adapters import ADAPTERS
from .config import get_settings
from .crawl.http import PoliteClient
from .crawl.robots import RobotsPolicy
from .log import setup_logging
from .scrape import ScrapeOrchestrator, iter_seed_file
from .store.db import Database

log = logging.getLogger(__name__)

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
    db = Database(settings.database.dsn)
    return settings, client, adapter, db


@app.command()
def enumerate(
    vendor: str = typer.Option("thermofisher", "--vendor", "-v"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max product URLs to list."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """List product URLs from the vendor's robots-allowed sitemaps (no pages fetched)."""
    setup_logging(verbose=verbose)
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
    resume: bool = typer.Option(False, "--resume", help="Skip products already in the DB (safe to re-run a long crawl)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Enumerate and validate without fetching or storing."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Scrape products: fetch pages concurrently, store image bytes + metadata rows."""
    setup_logging(verbose=verbose)
    settings, client, adapter, db = _build(vendor, concurrency=concurrency)
    try:
        if seed is not None:
            refs = adapter.seed(iter_seed_file(seed))
        else:
            refs = adapter.enumerate(limit=limit)
        if resume:
            done = db.scraped_catalogs(vendor)
            typer.echo(f"resume: skipping {len(done)} already-scraped products")
            refs = (r for r in refs if r.catalog_number not in done)
        orch = ScrapeOrchestrator(settings, client, adapter, db)
        summary = orch.run(refs, download_images=not no_images, dry_run=dry_run)
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
def report(
    vendor: str = typer.Option("thermofisher", "--vendor", "-v"),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Demonstrate cross-image queries over the stored corpus (a phase-2 preview)."""
    setup_logging(verbose=verbose)
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


@app.command()
def detect(
    tier: str = typer.Option("0", "--tier", "-t", help="Which tier(s) to run: 0, 1, or all."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Run forensic detectors over the stored corpus, writing rows into `findings`."""
    setup_logging(verbose=verbose)
    from .detect import tier0

    settings = get_settings()
    db = Database(settings.database.dsn)
    try:
        if tier in {"0", "all"}:
            counts = tier0.run_all(db)
            for name, n in counts.items():
                typer.echo(f"tier0.{name:20s} {n} findings")
        if tier in {"1", "all"}:
            from .detect import tier1

            counts = tier1.run_all(db)
            for name, n in counts.items():
                typer.echo(f"tier1.{name:20s} {n} findings")
    finally:
        db.close()


@app.command()
def findings(
    limit: int = typer.Option(25, "--limit", "-n"),
    finding_type: str = typer.Option(None, "--type", help="Filter by finding_type."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """List top findings by score (apparent anomalies flagged for human review)."""
    setup_logging(verbose=verbose)
    settings = get_settings()
    db = Database(settings.database.dsn)
    try:
        where = "WHERE finding_type = %s" if finding_type else ""
        params: list = [finding_type] if finding_type else []
        # Parameterize LIMIT to avoid any SQL injection surface.
        params.append(limit)
        rows = db.conn.execute(
            f"""
            SELECT finding_type, severity, n_products, provenance_pair, finding_key, detail
            FROM findings {where}
            ORDER BY score DESC, n_products DESC
            LIMIT %s
            """,
            params,
        ).fetchall()
        typer.echo(f"{'type':20s} {'sev':7s} {'prods':5s} {'provenance':22s} key")
        for r in rows:
            typer.echo(
                f"{r['finding_type']:20s} {r['severity'] or '':7s} {r['n_products'] or 0:5d} "
                f"{r['provenance_pair'] or '':22s} {r['finding_key']}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    app()
