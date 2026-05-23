"""
main.py — Entry point: argument parsing and logging setup.

Run with:
    python main.py --source ~/Downloads --dest ~/Organized
    python main.py --source ~/Downloads --dest ~/Organized --dry-run
    python main.py --source ~/Downloads --dest ~/Organized --workers 4
"""

import argparse
import logging
import sys
from pathlib import Path

from organizer import FileOrganizer


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOG_FILE = "organizer.log"

def setup_logging(verbose: bool) -> None:
    """Configure root logger to write to both the console and a log file.

    Args:
        verbose: When ``True``, the console handler shows DEBUG messages.
                 The file handler always captures DEBUG and above.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Console handler ---
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)
    root.addHandler(console)

    # --- File handler (always verbose) ---
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Define and parse command-line arguments."""
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

    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        metavar="DIR",
        help="Directory to scan (searched recursively).",
    )
    parser.add_argument(
        "--dest",
        required=True,
        type=Path,
        metavar="DIR",
        help="Root directory where category folders will be created.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would happen without moving any files.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Number of parallel worker processes for hashing. "
            "Defaults to the number of logical CPU cores."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Print DEBUG-level messages to the console.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_args(args: argparse.Namespace) -> None:
    """Raise ``SystemExit`` with a clear message if arguments are invalid.

    Args:
        args: Parsed namespace from :func:`parse_args`.
    """
    if not args.source.exists():
        sys.exit(f"Error: source directory does not exist: {args.source}")

    if not args.source.is_dir():
        sys.exit(f"Error: source is not a directory: {args.source}")

    if args.workers is not None and args.workers < 1:
        sys.exit("Error: --workers must be a positive integer.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    setup_logging(verbose=args.verbose)
    validate_args(args)

    logger = logging.getLogger(__name__)
    logger.info("File Organizer started.")

    organizer = FileOrganizer(
        source=args.source,
        destination=args.dest,
        dry_run=args.dry_run,
        workers=args.workers,
    )
    organizer.run()

    logger.info("Log saved to: %s", LOG_FILE)


if __name__ == "__main__":
    main()
