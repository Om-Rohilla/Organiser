"""
main.py — Entry point: argument parsing, Rich UI setup, and run orchestration.

Run with:
    python main.py --source ~/Downloads --dest ~/Organized
    python main.py --source ~/Downloads --dest ~/Organized --dry-run
    python main.py --source ~/Downloads --dest ~/Organized --workers 4 --verbose
"""

import argparse
import logging
import sys
from pathlib import Path

from rich.logging import RichHandler

import ui
from organizer import FileOrganizer


# ── Logging ───────────────────────────────────────────────────────────────────

LOG_FILE = "organizer.log"


def setup_logging(verbose: bool) -> None:
    """Configure logging:
    - Console  → RichHandler  (beautiful coloured output, respects --verbose)
    - Log file → FileHandler  (always captures DEBUG and above)
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rich console handler — INFO by default, DEBUG if --verbose
    rich_handler = RichHandler(
        console=ui.console,
        show_path=False,
        rich_tracebacks=True,
        markup=True,
    )
    rich_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(rich_handler)

    # Plain file handler — always full detail
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


# ── CLI args ──────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="file-organizer",
        description=(
            "Scan a directory, sort files into category sub-folders, "
            "and detect content-identical duplicates using MD5 hashing."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python main.py --source ~/Downloads --dest ~/Organized
  python main.py --source ~/Downloads --dest ~/Organized --dry-run
  python main.py --source ~/Downloads --dest ~/Organized --workers 4 --verbose
        """,
    )
    parser.add_argument("--source",   required=True, type=Path, metavar="DIR",
                        help="Directory to scan (searched recursively).")
    parser.add_argument("--dest",     required=True, type=Path, metavar="DIR",
                        help="Root directory where category folders will be created.")
    parser.add_argument("--dry-run",  action="store_true", default=False,
                        help="Show what would happen without moving any files.")
    parser.add_argument("--workers",  type=int, default=None, metavar="N",
                        help="Parallel hashing processes (default: all CPU cores).")
    parser.add_argument("--verbose",  action="store_true", default=False,
                        help="Print DEBUG-level messages to the console.")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not args.source.exists():
        ui.console.print(f"[error]✗  Source does not exist:[/] {args.source}")
        sys.exit(1)
    if not args.source.is_dir():
        ui.console.print(f"[error]✗  Source is not a directory:[/] {args.source}")
        sys.exit(1)
    if args.workers is not None and args.workers < 1:
        ui.console.print("[error]✗  --workers must be a positive integer.[/]")
        sys.exit(1)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    setup_logging(verbose=args.verbose)
    validate_args(args)

    # ── 1. Banner + config ────────────────────────────────────────────────────
    ui.print_banner()
    ui.print_config(
        source=args.source.resolve(),
        dest=args.dest.resolve(),
        dry_run=args.dry_run,
        workers=args.workers,
    )

    # ── 2. Build organizer & wire UI callbacks ────────────────────────────────
    organizer = FileOrganizer(
        source=args.source,
        destination=args.dest,
        dry_run=args.dry_run,
        workers=args.workers,
    )

    # Wire per-file Rich display callbacks
    organizer._on_move      = lambda src, dst: ui.log_move(src, dst, args.dry_run)
    organizer._on_duplicate = lambda path:     ui.log_duplicate(path)
    organizer._on_error     = lambda path, exc: ui.log_error(path, exc)

    # ── 3. Collect files ──────────────────────────────────────────────────────
    files = organizer._collect_files()

    if not files:
        ui.console.print("[warning]⚠  No files found in the source directory.[/]")
        return

    ui.console.print(
        f"[info]  Found [bold]{len(files)}[/] file(s) to process.[/]\n"
    )

    # ── 4. Hash with live progress bar ────────────────────────────────────────
    with ui.make_progress() as progress:
        task = progress.add_task(
            "🔑  Computing MD5 hashes…", total=len(files)
        )
        organizer._on_hashed = lambda: progress.advance(task)
        hash_map = organizer._hash_files(files)

    # ── 5. Deduplicate ────────────────────────────────────────────────────────
    duplicates = organizer._find_duplicates(hash_map)

    # ── 6. Move files ─────────────────────────────────────────────────────────
    ui.console.print()
    organizer._move_files(files, duplicates)

    # ── 7. Rich summary + log footer ─────────────────────────────────────────
    ui.print_summary(organizer.stats, args.dry_run)
    logging.getLogger(__name__).info("Log saved to: %s", LOG_FILE)


if __name__ == "__main__":
    main()
