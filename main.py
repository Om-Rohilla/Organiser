"""
main.py — Entry point: argument parsing, Rich UI setup, and run orchestration.

Run with:
    python main.py --source ~/Downloads --dest ~/Organized
    python main.py --source ~/Downloads --dest ~/Organized --dry-run
    python main.py --source ~/Downloads --dest ~/Organized --fresh   ← safe reset
    python main.py --source ~/Downloads --dest ~/Organized --undo    ← undo last run
    python main.py --source ~/Downloads --dest ~/Organized --workers 4 --verbose
"""

import argparse
import logging
import os
import secrets
import signal
import shutil
import sys
from datetime import datetime, timezone
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

    # Restrict log file to owner read/write only (0o600).
    # The log contains full file paths which are private information.
    try:
        os.chmod(LOG_FILE, 0o600)
    except OSError:
        pass   # non-fatal — best effort


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
  python main.py --source ~/Downloads --dest ~/Organized
  python main.py --source ~/Downloads --dest ~/Organized --dry-run
  python main.py --source ~/Downloads --dest ~/Organized --fresh
  python main.py --undo
  python main.py --source ~/Downloads --dest ~/Organized --workers 4 --verbose
        """,
    ) 
    parser.add_argument("--source",   required=False, type=Path, metavar="DIR", default=None,
                        help="Directory to scan (searched recursively). Not needed with --undo.")
    parser.add_argument("--dest",     required=False, type=Path, metavar="DIR", default=None,
                        help="Root directory where category folders will be created. Not needed with --undo.")
    parser.add_argument("--dry-run",  action="store_true", default=False,
                        help="Show what would happen without moving any files.")
    parser.add_argument("--workers",  type=int, default=None, metavar="N",
                        help="Parallel hashing processes (default: all CPU cores).")
    parser.add_argument("--verbose",  action="store_true", default=False,
                        help="Print DEBUG-level messages to the console.")
    parser.add_argument("--undo",     action="store_true", default=False,
                        help="Reverse the last run using the saved journal file.")
    parser.add_argument("--fresh",    action="store_true", default=False,
                        help=(
                            "Safely move the existing destination to a timestamped "
                            "backup before starting (e.g. Organized_backup_2026-05-24/). "
                            "NEVER deletes files. Use this instead of 'rm -rf'."
                        ))
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    from security import SecurityError, assert_safe_path

    if args.undo:
        return   # --undo doesn't need --source or --dest

    # For all other modes, --source and --dest are required
    if args.source is None or args.dest is None:
        ui.console.print("[error]✗  --source and --dest are required (unless using --undo)[/]")
        ui.console.print("  Example: [bold].venv/bin/python3 main.py --source ~/Downloads --dest ~/Organized[/]")
        sys.exit(1)

    # ── Security: path traversal guard ────────────────────────────────
    for flag, val in (("--source", args.source), ("--dest", args.dest)):
        try:
            assert_safe_path(val, label=flag)
        except SecurityError as exc:
            ui.console.print(f"[error]✗  Security violation in {flag}:[/] {exc}")
            sys.exit(2)

    if not args.source.exists():
        ui.console.print(f"[error]✗  Source does not exist:[/] {args.source}")
        sys.exit(1)
    if not args.source.is_dir():
        ui.console.print(f"[error]✗  Source is not a directory:[/] {args.source}")
        sys.exit(1)

    # ── Security: source must not BE the destination ──────────────────
    if args.source.resolve() == args.dest.resolve():
        ui.console.print("[error]✗  --source and --dest must be different directories.[/]")
        sys.exit(1)

    # ── Security: block known dangerous system directories as --dest ───
    from security import assert_safe_destination
    try:
        assert_safe_destination(args.dest)
    except SecurityError as exc:
        ui.console.print(f"[error]✗  {exc}[/]")
        sys.exit(2)

    # ── Security: --dest itself must not be a symlink ──────────────────
    # An attacker could pre-create ~/Organized as a symlink to /etc,
    # causing all sorted files to land inside the system directory.
    if args.dest.is_symlink():
        ui.console.print(
            f"[error]✗  --dest '{args.dest}' is a symbolic link. "
            "Use the real target path directly.[/]"
        )
        sys.exit(2)

    if args.workers is not None and args.workers < 1:
        ui.console.print("[error]✗  --workers must be a positive integer.[/]")
        sys.exit(1)

    # ── Security: cap worker threads to prevent OOM ───────────────────────────
    from security import check_workers_count
    if args.workers is not None:
        try:
            check_workers_count(args.workers)
        except SecurityError as exc:
            ui.console.print(f"[error]✗  {exc}[/]")
            sys.exit(2)




# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    setup_logging(verbose=args.verbose)
    validate_args(args)

    journal_path = Path(__file__).resolve().parent / JOURNAL_FILENAME

    # ── Register signal handler to clean up orphaned temp files ──────────────
    # If the process is killed (Ctrl-C or SIGTERM) during the atomic
    # journal write, a .tmp file is left behind in the project directory.
    # This handler removes any such orphans so the next run starts clean.
    def _cleanup_signal_handler(signum: int, frame: object) -> None:
        proj_dir = Path(__file__).resolve().parent
        for tmp in proj_dir.glob("*.tmp"):
            try:
                tmp.unlink()
            except OSError:
                pass
        sys.exit(128 + signum)   # standard exit code convention for signals

    signal.signal(signal.SIGINT,  _cleanup_signal_handler)
    signal.signal(signal.SIGTERM, _cleanup_signal_handler)

    # ── 0a. --undo: reverse last run ─────────────────────────────────────────
    if args.undo:

        ui.print_banner()
        ui.console.print("  [warning]⚠  UNDO mode — reversing last run[/]\n")
        if not journal_path.exists():
            ui.console.print(
                f"  [error]✗  No journal found at:[/] [path]{journal_path}[/]"
            )
            ui.console.print(
                "  Run a normal (non-dry-run) pass first to create a journal."
            )
            sys.exit(1)
        try:
            ok, fail = MoveJournal.undo(journal_path)
            ui.console.print(
                f"  [success]✔  Undo complete:[/] {ok} restored, {fail} failed"
            )
            if ok > 0:
                journal_path.unlink(missing_ok=True)
        except Exception as exc:
            ui.console.print(f"  [error]✗  Undo failed:[/] {exc}")
            sys.exit(1)
        return

    # ── 0b. --fresh: safely back up existing destination ─────────────────────
    dest_resolved = args.dest.resolve()
    if args.fresh and dest_resolved.exists():

        # UTC timestamp + 6-char random hex — prevents same-second collision
        # and prevents an attacker predicting/claiming the backup path name.
        timestamp   = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        rand_suffix = secrets.token_hex(3)   # 6 chars, e.g. 'a3f91c'
        backup_path = dest_resolved.parent / f"{dest_resolved.name}_backup_{timestamp}_{rand_suffix}"
        ui.print_banner()
        ui.console.print("  [warning]⚠  --fresh: existing destination detected[/]")
        ui.console.print(f"     Source : [path]{dest_resolved}[/]")
        ui.console.print(f"     Backup : [path]{backup_path}[/]")
        ui.console.print("")
        try:
            shutil.move(str(dest_resolved), str(backup_path))
            ui.console.print(
                "  [success]✔  Backup complete — your files are safe.[/]"
            )
            ui.console.print(
                f"     [muted]Backed up to:[/] [path]{backup_path}[/]"
            )
            ui.console.print("  Starting fresh run…\n")
        except OSError as exc:
            ui.console.print(f"  [error]✗  Backup failed:[/] {exc}")
            sys.exit(1)

    # ── 1. Banner + config ────────────────────────────────────────────────────
    ui.print_banner()

    # Warn if destination already has files and --fresh was not used
    if (
        dest_resolved.exists()
        and dest_resolved.is_dir()
        and any(dest_resolved.iterdir())
        and not args.fresh
    ):
        ui.console.print(
            "  [warning]⚠  Destination already contains files.[/]"
        )
        ui.console.print(
            f"     [path]{dest_resolved}[/]"
        )
        ui.console.print("")
        ui.console.print(
            "  The organiser will merge new files into it (safe)."
        )
        ui.console.print(
            "  For a clean re-run without losing anything, use [bold]--fresh[/]:"
        )
        ui.console.print(
            "     [bold]python main.py ... --fresh[/]"
            "   [muted]← backs up old folder, then starts clean[/]\n"
        )

    ui.print_config(
        source=args.source.resolve(),
        dest=dest_resolved,
        dry_run=args.dry_run,
        workers=args.workers,
    )

    # ── 2. Load optional organiser.toml config ────────────────────────────────
    cfg = load_config()
    cfg_path = find_config_file()
    if cfg_path:
        ui.console.print(f"  [muted]⚙  Config loaded:[/] [path]{cfg_path}[/]\n")

    # Apply user extensions / project markers from config
    import utils
    from utils import EXTENSION_MAP, MARKER_WEIGHTS
    utils.EXTENSION_MAP  = apply_config_to_extension_map(cfg, EXTENSION_MAP)
    utils.MARKER_WEIGHTS = apply_config_to_marker_weights(cfg, MARKER_WEIGHTS)

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

    # ── 4. Collect files + detect code projects ──────────────────────────────
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
                "🔑  Computing hashes…", total=len(files)
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

    # ── 8. Move whole project folders ────────────────────────────────────────
    if project_roots:
        ui.console.print()
        organizer._move_projects(project_roots)

    # ── 9. Save journal + Rich summary + log footer ───────────────────────────
    if organizer.journal and organizer.journal.op_count > 0:
        organizer.journal.save()
        ui.console.print(
            "  [muted]↩  To undo this run:[/] [bold]python main.py --undo[/]\n"
        )
    ui.print_summary(organizer.stats, args.dry_run)
    logging.getLogger(__name__).info("Log saved to: %s", LOG_FILE)


if __name__ == "__main__":
    from security import SecurityError
    try:
        main()
    except SecurityError as _sec_exc:
        # Top-level catcher: any SecurityError that escaped an internal handler
        # is printed clearly and exits with code 2 (security violation).
        import sys as _sys
        from rich.console import Console as _Console
        _Console().print(f"\n[bold red]✗  SECURITY VIOLATION:[/bold red] {_sec_exc}\n")
        _sys.exit(2)
