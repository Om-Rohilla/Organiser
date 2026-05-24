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
from config import apply_config_to_extension_map, apply_config_to_marker_weights, find_config_file, load_config
from journal import MoveJournal, JOURNAL_FILENAME
from organizer import FileOrganizer


# ── Logging ───────────────────────────────────────────────────────────────────

# Always write the log file next to main.py, regardless of where the
# user runs the command from. Using CWD caused the log to be "lost" when
# running from a different directory.
LOG_FILE = Path(__file__).resolve().parent / "organizer.log"


def setup_logging(verbose: bool) -> None:
    """Configure logging:
    - Console  → RichHandler  (WARNING+ only — Rich callbacks handle per-file output)
    - Log file → FileHandler  (always captures DEBUG and above)
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rich console handler — WARNING only so per-file INFO noise is suppressed.
    # All per-file feedback (moves, duplicates, errors) goes through Rich
    # UI callbacks instead, keeping the console clean and structured.
    rich_handler = RichHandler(
        console=ui.console,
        show_path=False,
        rich_tracebacks=True,
        markup=True,
    )
    rich_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
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
    parser.add_argument("--undo",     action="store_true", default=False,
                        help="Reverse the last run using the saved journal file.")
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

    # ── 0. Handle --undo before doing anything else ─────────────────────────
    journal_path = Path(__file__).resolve().parent / JOURNAL_FILENAME
    if args.undo:
        ui.print_banner()
        ui.console.print(f"  [warning]⚠  UNDO mode — reversing last run[/]\n")
        if not journal_path.exists():
            ui.console.print(f"  [error]✗  No journal found at:[/] [path]{journal_path}[/]")
            ui.console.print("  Run a normal (non-dry-run) pass first to create a journal.")
            sys.exit(1)
        try:
            ok, fail = MoveJournal.undo(journal_path)
            ui.console.print(f"  [success]✔  Undo complete:[/] {ok} restored, {fail} failed")
            if ok > 0:
                journal_path.unlink(missing_ok=True)   # clear journal after successful undo
        except Exception as exc:
            ui.console.print(f"  [error]✗  Undo failed:[/] {exc}")
            sys.exit(1)
        return

    # ── 1. Banner + config ────────────────────────────────────────────────────
    ui.print_banner()
    ui.print_config(
        source=args.source.resolve(),
        dest=args.dest.resolve(),
        dry_run=args.dry_run,
        workers=args.workers,
    )

    # ── 2. Load optional organiser.toml config ───────────────────────────────
    cfg = load_config()
    cfg_path = find_config_file()
    if cfg_path:
        ui.console.print(f"  [muted]⚙  Config loaded:[/] [path]{cfg_path}[/]\n")

    # Apply user extensions / project markers from config
    from utils import EXTENSION_MAP, MARKER_WEIGHTS
    import utils
    utils.EXTENSION_MAP   = apply_config_to_extension_map(cfg, EXTENSION_MAP)
    utils.MARKER_WEIGHTS  = apply_config_to_marker_weights(cfg, MARKER_WEIGHTS)

    # ── 3. Build organizer & wire UI callbacks ────────────────────────────────
    organizer = FileOrganizer(
        source=args.source,
        destination=args.dest,
        dry_run=args.dry_run,
        workers=args.workers,
    )

    # Wire per-file Rich display callbacks
    organizer._on_move         = lambda src, dst: ui.log_move(src, dst, args.dry_run)
    organizer._on_project_move = lambda d, dst:   ui.log_project_move(d, dst, args.dry_run)
    organizer._on_duplicate    = lambda path:      ui.log_duplicate(path)
    organizer._on_error        = lambda path, exc: ui.log_error(path, exc)

    # Wire journal (skipped in dry-run — nothing real to undo)
    if not args.dry_run:
        organizer.journal = MoveJournal(journal_path, dry_run=False)

    # ── 4. Collect files + detect code projects ─────────────────────────────
    files, project_roots = organizer._collect_files_and_projects()

    if not files and not project_roots:
        ui.console.print("[warning]⚠  No files found in the source directory.[/]")
        return

    parts = []
    if files:
        parts.append(f"[bold]{len(files)}[/] file(s)")
    if project_roots:
        parts.append(f"[bold]{len(project_roots)}[/] code project(s)")
    ui.console.print(f"[info]  Found {' + '.join(parts)} to process.[/]\n")

    # ── 5. Hash with live progress bar (files only — projects aren't hashed) ──
    if files:
        with ui.make_progress() as progress:
            task = progress.add_task(
                "🔑  Computing MD5 hashes…", total=len(files)
            )
            organizer._on_hashed = lambda: progress.advance(task)
            hash_map = organizer._hash_files(files)

        # ── 6. Deduplicate ────────────────────────────────────────────────────
        duplicates = organizer._find_duplicates(hash_map)
        ui.console.print()
        # ── 7. Move individual files ──────────────────────────────────────────
        organizer._move_files(files, duplicates)
    else:
        duplicates = set()

    # ── 8. Move whole project folders ─────────────────────────────────────────
    if project_roots:
        ui.console.print()
        organizer._move_projects(project_roots)

    # ── 9. Save journal + Rich summary + log footer ───────────────────────────
    if organizer.journal and organizer.journal.op_count > 0:
        organizer.journal.save()
        ui.console.print(
            f"  [muted]↩  To undo this run:[/] [path]python main.py --undo[/]\n"
        )
    ui.print_summary(organizer.stats, args.dry_run)
    logging.getLogger(__name__).info("Log saved to: %s", LOG_FILE)


if __name__ == "__main__":
    main()
