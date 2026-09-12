"""CLI entry point for find-hub-tracker."""

import asyncio
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import click
import structlog
from rich.console import Console
from rich.table import Table
from sqlalchemy import Engine
from structlog._log_levels import NAME_TO_LEVEL

from find_hub_tracker.config import Settings, get_settings
from find_hub_tracker.db import queries
from find_hub_tracker.db.core import get_engine, get_session, run_migrations

console = Console()


def init_engine(settings: Settings) -> Engine:
    engine = get_engine(settings)
    run_migrations(engine)
    return engine


@contextmanager
def init_session(settings: Settings):
    engine = init_engine(settings)
    with get_session(engine) as session:
        yield session


def _configure_logging(level: str = "INFO") -> None:
    """Configure structlog for console output."""
    log_level = NAME_TO_LEVEL.get(level.lower(), NAME_TO_LEVEL["info"])
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@click.group()
@click.option(
    "--log-level", default=None, help="Override log level (DEBUG, INFO, WARNING, ERROR)"
)
def cli(log_level: str | None) -> None:
    """Google Find Hub device tracker with Discord notifications."""
    settings = get_settings()
    level = log_level or settings.log_level
    _configure_logging(level)


@cli.command()
def start() -> None:
    """Start the polling daemon."""
    settings = get_settings()

    if not settings.discord_webhook_url:
        console.print(
            "[yellow]Warning:[/yellow] DISCORD_WEBHOOK_URL not set. "
            "Location updates will be stored locally but not posted to Discord."
        )

    from find_hub_tracker.app import App

    app = App(settings)
    asyncio.run(app.start())


@cli.command()
def status() -> None:
    """Show all devices and their last known locations."""
    settings = get_settings()

    with init_session(settings) as session:
        locations = queries.get_all_latest_locations(session)
        if not locations:
            console.print("[dim]No device data recorded yet.[/dim]")
            return

        table = Table(title="Device Status")
        table.add_column("Device", style="cyan")
        table.add_column("Type", style="dim")
        table.add_column("Latitude", justify="right")
        table.add_column("Longitude", justify="right")
        table.add_column("Accuracy", justify="right")
        table.add_column("Battery", justify="right")
        table.add_column("Last Seen")

        for loc in locations:
            battery = (
                f"{loc.battery_percent}%" if loc.battery_percent is not None else "N/A"
            )
            accuracy = (
                f"{loc.accuracy_meters:.0f}m"
                if loc.accuracy_meters is not None
                else "N/A"
            )
            table.add_row(
                loc.device_name,
                loc.device_type,
                f"{loc.latitude:.6f}",
                f"{loc.longitude:.6f}",
                accuracy,
                battery,
                loc.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"),
            )

        console.print(table)


@cli.command()
@click.argument("device")
@click.option("--days", default=7, help="Number of days of history to show")
def history(device: str, days: int) -> None:
    """Show location history for a device."""
    settings = get_settings()

    with init_session(settings) as session:
        # Resolve device name to device_id
        all_devices = queries.get_all_devices(session)
        device_id = None
        for dev in all_devices:
            if dev.name.lower() == device.lower():
                device_id = dev.id
                break

        if device_id is None:
            console.print(f"[red]Device '{device}' not found.[/red]")
            known = [d.name for d in all_devices]
            if known:
                console.print(f"[dim]Known devices: {', '.join(known)}[/dim]")
            return

        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        locations = queries.get_device_history(session, device_id, start, end)

        if not locations:
            msg = f"No history found for '{device}' in the last {days} days."
            console.print(f"[dim]{msg}[/dim]")
            return

        table = Table(title=f"Location History: {device} (last {days} days)")
        table.add_column("Timestamp")
        table.add_column("Latitude", justify="right")
        table.add_column("Longitude", justify="right")
        table.add_column("Accuracy", justify="right")
        table.add_column("Battery", justify="right")
        table.add_column("Maps Link", style="dim")

        for loc in locations:
            battery = (
                f"{loc.battery_percent}%" if loc.battery_percent is not None else "N/A"
            )
            accuracy = (
                f"{loc.accuracy_meters:.0f}m"
                if loc.accuracy_meters is not None
                else "N/A"
            )
            table.add_row(
                loc.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                f"{loc.latitude:.6f}",
                f"{loc.longitude:.6f}",
                accuracy,
                battery,
                loc.maps_url,
            )

        console.print(table)


@cli.command()
def devices() -> None:
    """List all known devices with types and battery."""
    settings = get_settings()

    with init_session(settings) as session:
        all_devices = queries.get_all_devices(session)
        if not all_devices:
            console.print("[dim]No devices registered yet.[/dim]")
            return

        # Get latest locations for battery info
        latest = queries.get_all_latest_locations(session)
        latest_map = {loc.device_id: loc for loc in latest}

        table = Table(title="Registered Devices")
        table.add_column("Name", style="cyan")
        table.add_column("Type")
        table.add_column("Model", style="dim")
        table.add_column("Battery", justify="right")
        table.add_column("Last Location", style="dim")

        for dev in all_devices:
            loc = latest_map.get(dev.id)
            battery = "N/A"
            last_loc = "No data"
            if loc:
                if loc.battery_percent is not None:
                    battery = f"{loc.battery_percent}%"
                last_loc = f"{loc.latitude:.4f}, {loc.longitude:.4f}"

            table.add_row(
                dev.name,
                dev.device_type,
                dev.model or "N/A",
                battery,
                last_loc,
            )


@cli.command("test-discord")
def test_discord() -> None:
    """Send a test message to verify webhook configuration."""
    settings = get_settings()

    if not settings.discord_webhook_url:
        console.print("[red]DISCORD_WEBHOOK_URL is not set in .env[/red]")
        sys.exit(1)

    async def _test() -> None:
        from find_hub_tracker.discord import DiscordPublisher

        publisher = DiscordPublisher(
            webhook_url=settings.discord_webhook_url,
            battery_webhook_url=settings.battery_webhook_url,
        )
        try:
            success = await publisher.post_test()
            if success:
                console.print("[green]Test message sent successfully![/green]")
            else:
                console.print("[red]Failed to send test message.[/red]")
                sys.exit(1)
        finally:
            await publisher.close()

    asyncio.run(_test())


@cli.command()
def auth() -> None:
    """Run the one-time Google authentication flow (requires Chrome)."""
    console.print("[bold]Google Find Hub Authentication[/bold]")
    console.print("This will open Chrome for you to log in to your Google account.")
    console.print(f"Credentials will be saved to {get_settings().auth_secrets_path}\n")

    async def _auth() -> None:
        from find_hub_tracker.google_fmd import GoogleFindMyDevices

        fmd = GoogleFindMyDevices()
        try:
            await fmd.authenticate()
            console.print("[green]Authentication successful![/green]")
        except Exception as e:
            console.print(f"[red]Authentication failed: {e}[/red]")
            sys.exit(1)

    asyncio.run(_auth())


@cli.command("db-migrate")
def db_migrate() -> None:
    """Run pending database migrations."""
    settings = get_settings()

    with init_session(settings):
        console.print("[green]Migrations complete.[/green]")


@cli.command("db-prune")
@click.option("--days", default=None, type=int, help="Override HISTORY_RETENTION_DAYS")
def db_prune(days: int | None) -> None:
    """Manually prune old location records."""
    settings = get_settings()
    retention = days or settings.history_retention_days

    with init_session(settings) as session:
        count = queries.prune_old_locations(session, retention)
        console.print(
            f"[green]Pruned {count} records older than {retention} days.[/green]"
        )


if __name__ == "__main__":
    cli()
