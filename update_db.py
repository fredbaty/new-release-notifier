"""CLI tool to ignore/unignore artists by searching beets database."""

import typer

from src.beets_reader import BeetsReader
from src.config import load_config
from src.database import NotificationDatabase

app = typer.Typer()


def search_artists(beets: BeetsReader, search_term: str) -> dict[str, str]:
    """Search beets for artists matching the search term (case-insensitive)."""
    all_artists = beets.get_all_artists_with_mb_ids()
    search_lower = search_term.lower()
    return {
        name: mb_id
        for name, mb_id in all_artists.items()
        if search_lower in name.lower()
    }


@app.command()
def ignore(
    search_terms: list[str] = typer.Argument(..., help="Artist name(s) to search for"),
    config_path: str = typer.Option(
        "data/app_config.yml", "--config", help="Path to configuration file"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Ignore artists matching the search term(s)."""
    config = load_config(config_path)
    beets = BeetsReader(config.databases.beets_db)
    db = NotificationDatabase(config.databases.notifications_db)

    # Collect matches for all search terms
    all_matches: dict[str, str] = {}
    for search_term in search_terms:
        matches = search_artists(beets, search_term)
        if not matches:
            typer.echo(f"No artists found matching '{search_term}'")
        else:
            all_matches.update(matches)

    if not all_matches:
        typer.echo("\nNo artists found for any search term.")
        raise typer.Exit(1)

    typer.echo(f"\nFound {len(all_matches)} artist(s) total:\n")
    for name, mb_id in all_matches.items():
        ignored = db.is_artist_ignored(mb_id)
        status = " [already ignored]" if ignored else ""
        typer.echo(f"  - {name}{status}")
        typer.echo(f"    MB ID: {mb_id}")

    # Filter to only non-ignored artists
    to_ignore = {
        name: mb_id
        for name, mb_id in all_matches.items()
        if not db.is_artist_ignored(mb_id)
    }

    if not to_ignore:
        typer.echo("\nAll matching artists are already ignored.")
        raise typer.Exit(0)

    if not yes:
        typer.echo("")
        confirm = typer.confirm(f"Ignore {len(to_ignore)} artist(s)?")
        if not confirm:
            typer.echo("Cancelled.")
            raise typer.Exit(0)

    for name, mb_id in to_ignore.items():
        db.ignore_artist(mb_id)
        typer.echo(f"Ignored: {name}")

    typer.echo(f"\nDone. Ignored {len(to_ignore)} artist(s).")


@app.command()
def unignore(
    search_term: str = typer.Argument(..., help="Artist name to search for"),
    config_path: str = typer.Option(
        "data/app_config.yml", "--config", help="Path to configuration file"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Unignore artists matching the search term."""
    config = load_config(config_path)
    beets = BeetsReader(config.databases.beets_db)
    db = NotificationDatabase(config.databases.notifications_db)

    matches = search_artists(beets, search_term)

    if not matches:
        typer.echo(f"No artists found matching '{search_term}'")
        raise typer.Exit(1)

    typer.echo(f"\nFound {len(matches)} artist(s) matching '{search_term}':\n")
    for name, mb_id in matches.items():
        ignored = db.is_artist_ignored(mb_id)
        status = " [ignored]" if ignored else " [not ignored]"
        typer.echo(f"  - {name}{status}")
        typer.echo(f"    MB ID: {mb_id}")

    # Filter to only ignored artists
    to_unignore = {
        name: mb_id for name, mb_id in matches.items() if db.is_artist_ignored(mb_id)
    }

    if not to_unignore:
        typer.echo("\nNo matching artists are currently ignored.")
        raise typer.Exit(0)

    if not yes:
        typer.echo("")
        confirm = typer.confirm(f"Unignore {len(to_unignore)} artist(s)?")
        if not confirm:
            typer.echo("Cancelled.")
            raise typer.Exit(0)

    for name, mb_id in to_unignore.items():
        db.unignore_artist(mb_id)
        typer.echo(f"Unignored: {name}")

    typer.echo(f"\nDone. Unignored {len(to_unignore)} artist(s).")


@app.command()
def list_ignored(
    config_path: str = typer.Option(
        "data/app_config.yml", "--config", help="Path to configuration file"
    ),
):
    """List all ignored artists."""
    config = load_config(config_path)
    beets = BeetsReader(config.databases.beets_db)
    db = NotificationDatabase(config.databases.notifications_db)

    ignored_ids = set(db.get_ignored_artists())
    if not ignored_ids:
        typer.echo("No artists are currently ignored.")
        raise typer.Exit(0)

    # Get artist names from beets for the ignored IDs
    all_artists = beets.get_all_artists_with_mb_ids()
    ignored_artists = {
        name: mb_id for name, mb_id in all_artists.items() if mb_id in ignored_ids
    }

    typer.echo(f"\nIgnored artists ({len(ignored_ids)} total):\n")
    for name, mb_id in sorted(ignored_artists.items()):
        typer.echo(f"  - {name}")
        typer.echo(f"    MB ID: {mb_id}")

    # Check for any ignored IDs not found in beets
    found_ids = set(ignored_artists.values())
    orphaned = ignored_ids - found_ids
    if orphaned:
        typer.echo(f"\n{len(orphaned)} ignored ID(s) not found in beets:")
        for mb_id in orphaned:
            typer.echo(f"  - {mb_id}")


if __name__ == "__main__":
    app()
