"""
ui.py — Rich-powered terminal UI for File Organizer.

All console output is centralised here so organizer.py and main.py
stay focused on logic.  Import ``console`` anywhere you need to print.
"""

from pathlib import Path

from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# ── Shared console (import this wherever you need console.print) ──────────────

_THEME = Theme(
    {
        "info":    "bold cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error":   "bold red",
        "muted":   "dim white",
        "path":    "bright_cyan",
        "moved":   "bright_green",
        "dupe":    "bright_magenta",
        "skipped": "yellow",
    }
)

console = Console(theme=_THEME, highlight=False)


# ── Banner ────────────────────────────────────────────────────────────────────

def print_banner() -> None:
    """Render the opening title banner."""
    title = Text.assemble(
        ("🗂️  File Organizer\n", "bold cyan"),
        ("Scan · Sort · Deduplicate · Log", "dim white"),
    )
    console.print(
        Panel(
            Align.center(title),
            border_style="bright_cyan",
            padding=(1, 8),
        )
    )
    console.print()


# ── Configuration panel ───────────────────────────────────────────────────────

def print_config(
    source: Path,
    dest: Path,
    dry_run: bool,
    workers: "int | None",
) -> None:
    """Show the run configuration in a neat panel."""
    tbl = Table(box=None, show_header=False, padding=(0, 2))
    tbl.add_column(style="muted", no_wrap=True)
    tbl.add_column(style="bold white")

    tbl.add_row("📁  Source",      f"[path]{source}[/]")
    tbl.add_row("📂  Destination", f"[path]{dest}[/]")
    tbl.add_row(
        "🔍  Mode",
        "[bold yellow]DRY-RUN — nothing will be moved[/]"
        if dry_run else
        "[bold green]LIVE — files will be moved[/]",
    )
    tbl.add_row(
        "⚙️   Workers",
        str(workers) if workers else "[muted]auto (all CPU cores)[/]",
    )

    console.print(
        Panel(tbl, title="[bold cyan]⚙  Configuration[/]", border_style="cyan")
    )
    console.print()


# ── Hashing progress bar ──────────────────────────────────────────────────────

def make_progress() -> Progress:
    """Return a Rich Progress bar for the hashing phase."""
    return Progress(
        SpinnerColumn(spinner_name="dots2", style="bold cyan"),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=42, style="cyan", complete_style="bold green"),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )


# ── Per-file event lines ──────────────────────────────────────────────────────

def log_move(src: Path, dst: Path, dry_run: bool) -> None:
    prefix = "  [bold yellow][DRY-RUN][/] " if dry_run else "  "
    console.print(
        f"{prefix}[moved]✔[/]  [path]{src.name}[/]"
        f"  [muted]→[/]  [moved]{dst.parent.name}/{dst.name}[/]"
    )


def log_duplicate(path: Path) -> None:
    console.print(f"  [dupe]⊗  Duplicate (skipped):[/]  [path]{path.name}[/]")


def log_error(path: Path, exc: Exception) -> None:
    console.print(f"  [error]✗  Error:[/]  [path]{path.name}[/]  [muted]—[/]  {exc}")


# ── Summary panel ─────────────────────────────────────────────────────────────

def print_summary(stats: "dict[str, int]", dry_run: bool) -> None:
    """Render the final run-summary panel."""
    tbl = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        padding=(0, 3),
        min_width=46,
    )
    tbl.add_column("Metric",  style="muted",    no_wrap=True)
    tbl.add_column("Count",   justify="right",   style="bold white", min_width=6)
    tbl.add_column("",        justify="center",  min_width=3)

    rows = [
        ("📄  Files scanned",    "scanned",    "",               ""),
        ("✅  Files moved",      "moved",      "[green]✓[/]",    ""),
        ("⊗   Duplicates found", "duplicates", "[magenta]![/]",  "[green]✓[/]"),
        ("⏭   Skipped",          "skipped",    "",               ""),
        ("❌  Errors",           "errors",     "[red]✗[/]",      "[green]✓[/]"),
    ]

    for label, key, bad_icon, good_icon in rows:
        val = stats[key]
        if key in ("duplicates", "errors"):
            icon = bad_icon if val else good_icon
        else:
            icon = good_icon if val else ""
        tbl.add_row(label, str(val), icon)

    mode = " [bold yellow](dry-run)[/]" if dry_run else ""
    console.print()
    console.print(
        Panel(
            Align.center(tbl),
            title=f"[bold green]✔  Run Complete{mode}[/]",
            border_style="green",
            padding=(1, 4),
        )
    )
    console.print(Rule(style="dim"))
    console.print()
