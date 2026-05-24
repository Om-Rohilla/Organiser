"""
organizer.py — Core logic for scanning, hashing, and moving files.

Design decisions:
  - All heavy I/O (hashing) is done via a ``ProcessPoolExecutor`` so that
    multiple CPU cores are used in parallel.
  - The ``dry_run`` flag gates every destructive call (mkdir, rename/move).
    When True, the organizer only *describes* what it would do.
  - Logging goes to the file handler; Rich UI callbacks drive the console.
  - UI callbacks (_on_hashed, _on_move, _on_duplicate, _on_error) are
    optional callables set by main.py — keeping this module UI-agnostic.
"""

import hashlib
import logging
import shutil
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

from utils import get_category, is_code_project, safe_destination
from protocols import OnDuplicate, OnError, OnHashed, OnMove, OnProjectMove
from journal import MoveJournal

logger = logging.getLogger(__name__)

# Absolute path of this file's directory — used to prevent the organiser
# from accidentally treating its own folder as a source item.
_SELF_DIR: Path = Path(__file__).resolve().parent

# How many bytes we read at a time when computing MD5 hashes.
# 64 KB is a sweet spot: small enough to keep memory low, large enough to
# avoid excessive system-call overhead.
_HASH_CHUNK_SIZE = 65_536


# ---------------------------------------------------------------------------
# File hashing (runs in worker processes)
# ---------------------------------------------------------------------------
# We prefer xxHash (xxh3_128) over MD5 for two reasons:
#   1. Speed — xxHash runs at ~4-10 GB/s vs ~500 MB/s for MD5
#   2. No false cryptographic security needed — this is dedup, not auth
#
# If xxhash is not installed we silently fall back to MD5 so the tool
# keeps working without any extra installation step.

try:
    import xxhash as _xxhash
    _USE_XXHASH = True
except ImportError:
    _USE_XXHASH = False


def compute_hash(file_path: Path) -> tuple[Path, str | None]:
    """Compute a fast content hash of *file_path* for deduplication.

    Uses xxHash (xxh3_128) when available, falls back to MD5 otherwise.
    This function runs in a worker process and must be importable at the
    top level (no lambdas or closures).

    Args:
        file_path: The file to hash.

    Returns:
        A ``(file_path, hex_digest)`` tuple.  The digest is ``None`` when the
        file cannot be read (permission error, locked file, etc.).
    """
    try:
        with file_path.open("rb") as fh:
            if _USE_XXHASH:
                h = _xxhash.xxh3_128()
                while chunk := fh.read(_HASH_CHUNK_SIZE):
                    h.update(chunk)
                return file_path, h.hexdigest()
            else:
                import hashlib
                h = hashlib.md5()
                while chunk := fh.read(_HASH_CHUNK_SIZE):
                    h.update(chunk)
                return file_path, h.hexdigest()
    except OSError as exc:
        logger.warning("Cannot hash %s: %s", file_path, exc)
        return file_path, None


# Keep compute_md5 as a public alias so existing tests and external
# callers that import it directly continue to work unchanged.
compute_md5 = compute_hash


# ---------------------------------------------------------------------------
# Main organizer class
# ---------------------------------------------------------------------------

class FileOrganizer:
    """Scan a source directory and move files into categorised sub-folders.

    Args:
        source: Directory to scan (searched recursively).
        destination: Root directory where category folders will be created.
        dry_run: When ``True``, log what *would* happen but do nothing.
        workers: Number of parallel worker processes for hashing.
                 Defaults to ``None`` (uses ``os.cpu_count()``).
    """

    def __init__(
        self,
        source: Path,
        destination: Path,
        *,
        dry_run: bool = False,
        workers: int | None = None,
    ) -> None:
        self.source = source.resolve()
        self.destination = destination.resolve()
        self.dry_run = dry_run
        self.workers = workers

        # Populated after ``run()`` is called.
        self.stats: dict[str, int] = {
            "scanned": 0,
            "moved": 0,
            "skipped": 0,
            "duplicates": 0,
            "errors": 0,
            "projects": 0,    # whole project folders moved
        }

        # Optional move journal for --undo support (set by main.py)
        self.journal: MoveJournal | None = None

        # Optional UI callbacks — set by main.py to drive the Rich display.
        # Typed with Protocol classes from protocols.py for full IDE + mypy support.
        # Keeping them None by default means the organizer works without any UI.
        self._on_hashed:       OnHashed | None      = None  # () after each file hashed
        self._on_move:         OnMove | None         = None  # (src, dst) file moved
        self._on_project_move: OnProjectMove | None  = None  # (dir, dst) project moved
        self._on_duplicate:    OnDuplicate | None    = None  # (path) dupe skipped
        self._on_error:        OnError | None        = None  # (path, exc) on error

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Execute the full organise-and-deduplicate pipeline."""
        logger.debug("Source      : %s", self.source)
        logger.debug("Destination : %s", self.destination)
        logger.debug("Dry-run     : %s", self.dry_run)

        files, project_roots = self._collect_files_and_projects()

        if not files and not project_roots:
            logger.info("No files found in source directory. Nothing to do.")
            return

        logger.info(
            "Found %d file(s) and %d code project(s) to process.",
            len(files), len(project_roots),
        )

        hash_map  = self._hash_files(files)
        duplicates = self._find_duplicates(hash_map)
        self._move_files(files, duplicates)
        self._move_projects(project_roots)
        self._log_summary()

    # ------------------------------------------------------------------
    # Step 1 — Collect files + detect code projects
    # ------------------------------------------------------------------

    def _collect_files_and_projects(
        self,
    ) -> "tuple[list[Path], list[Path]]":
        """Scan ``self.source`` and separate individual files from project dirs.

        Top-level sub-directories of the source are checked via
        :func:`~utils.is_code_project`.  Recognised projects are returned
        separately so they can be moved as a whole unit, preserving their
        internal folder structure inside ``Code/``.

        Returns:
            ``(files, project_roots)`` — individual files to hash/move and
            project directories to move wholesale.
        """
        files: list[Path] = []
        project_roots: list[Path] = []

        for item in sorted(self.source.iterdir()):
            # Never touch anything already inside the destination tree.
            try:
                item.relative_to(self.destination)
                continue
            except ValueError:
                pass

            # Never move the organiser's own directory if it happens to live
            # inside the source tree (e.g. --source ~/Desktop).
            if item.resolve() == _SELF_DIR:
                logger.info("Skipping organiser directory: %s", item)
                continue

            if item.is_dir():
                if is_code_project(item):
                    logger.info("Code project detected: %s", item.name)
                    project_roots.append(item)
                    self.stats["scanned"] += 1
                else:
                    # Regular folder — recurse and collect individual files.
                    for path in item.rglob("*"):
                        if path.is_symlink():   # skip symlinks — avoids infinite loops
                            continue
                        if not path.is_file():
                            continue
                        try:
                            path.relative_to(self.destination)
                            continue
                        except ValueError:
                            pass
                        files.append(path)
                        self.stats["scanned"] += 1
            elif item.is_file():
                files.append(item)
                self.stats["scanned"] += 1

        return files, project_roots

    # ------------------------------------------------------------------
    # Step 2 — Hash (parallel)
    # ------------------------------------------------------------------

    def _hash_files(self, files: list[Path]) -> dict[str, list[Path]]:
        """Hash every file using a process pool.

        Returns:
            A mapping of ``md5_hex → [file_path, ...]``.
            Groups with more than one path are duplicates.
        """
        if not files:
            return {}
        logger.info("Hashing %d file(s) using multiprocessing …", len(files))
        hash_map: dict[str, list[Path]] = {}

        with ProcessPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(compute_hash, f): f for f in files}

            for future in as_completed(futures):
                file_path, digest = future.result()
                if self._on_hashed:
                    self._on_hashed()
                if digest is None:
                    self.stats["errors"] += 1
                    continue
                hash_map.setdefault(digest, []).append(file_path)

        return hash_map

    # ------------------------------------------------------------------
    # Step 3 — Find duplicates
    # ------------------------------------------------------------------

    def _find_duplicates(
        self, hash_map: dict[str, list[Path]]
    ) -> set[Path]:
        """Identify which files are duplicates (same content, different path).

        For each group of identical files we keep the *first* one
        (alphabetically by path) and mark the rest as duplicates.

        Args:
            hash_map: Mapping returned by ``_hash_files``.

        Returns:
            A set of paths that are considered duplicates and should be
            skipped during the move phase.
        """
        duplicates: set[Path] = set()

        for digest, paths in hash_map.items():
            if len(paths) <= 1:
                continue

            # Sort so the result is deterministic across runs.
            paths.sort()
            keeper, *dupes = paths

            # Log to file only — console display is handled by _on_duplicate callback.
            logger.info(
                "Duplicate detected (MD5: %s). Keeping: %s",
                digest,
                keeper,
            )
            for dupe in dupes:
                logger.info("  └─ duplicate (skipped): %s", dupe)
                if self._on_duplicate:
                    self._on_duplicate(dupe)
                duplicates.add(dupe)
                self.stats["duplicates"] += 1

        return duplicates

    # ------------------------------------------------------------------
    # Step 4 — Move
    # ------------------------------------------------------------------

    def _move_files(
        self, files: list[Path], duplicates: set[Path]
    ) -> None:
        """Move every non-duplicate file to the appropriate category folder.

        Uses a ``ThreadPoolExecutor`` so multiple moves run in parallel.
        Thread safety is achieved via ``_stats_lock`` (for stat counters)
        and ``_dest_lock`` (for the safe_destination check-and-move pair).
        This is most beneficial for cross-device moves where the OS copies
        data; for same-filesystem renames the improvement is still visible
        because directory-entry creation can overlap with I/O.
        """
        _stats_lock = threading.Lock()
        _dest_lock  = threading.Lock()

        def _move_one(file_path: Path) -> None:
            if file_path in duplicates:
                with _stats_lock:
                    self.stats["skipped"] += 1
                return

            category    = get_category(file_path)
            category_dir = self.destination / category
            self._ensure_dir(category_dir)

            # Lock around safe_destination + shutil.move so two threads
            # can't both claim the same target path simultaneously.
            with _dest_lock:
                target = safe_destination(category_dir, file_path)

                if self.dry_run:
                    logger.info("[DRY-RUN] Would move: %s → %s", file_path, target)
                    with _stats_lock:
                        self.stats["moved"] += 1
                    if self._on_move:
                        self._on_move(file_path, target)
                    return

                try:
                    shutil.move(str(file_path), str(target))
                except PermissionError as exc:
                    logger.error("Permission denied moving %s: %s", file_path, exc)
                    with _stats_lock:
                        self.stats["errors"] += 1
                    if self._on_error:
                        self._on_error(file_path, exc)
                    return
                except OSError as exc:
                    logger.error("Error moving %s: %s", file_path, exc)
                    with _stats_lock:
                        self.stats["errors"] += 1
                    if self._on_error:
                        self._on_error(file_path, exc)
                    return

            logger.info("Moved: %s → %s", file_path, target)
            with _stats_lock:
                self.stats["moved"] += 1
                if self.journal:
                    self.journal.record_file(file_path, target)
            if self._on_move:
                self._on_move(file_path, target)

        # I/O-bound → threads (not processes). Use same worker count as hashing.
        max_workers = self.workers or min(32, len(files) or 1)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            # list() forces iteration so exceptions surface immediately
            list(pool.map(_move_one, files))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _move_projects(self, project_roots: list[Path]) -> None:
        """Move entire code-project folders wholesale into ``Code/``.

        Each project folder lands at ``dest/Code/<project-name>/``,
        preserving every file and sub-folder inside it exactly as-is.
        Name collisions are resolved the same way as regular files
        (``my-app/`` → ``my-app_1/``).

        Args:
            project_roots: Directories identified as code projects.
        """
        if not project_roots:
            return

        code_dir = self.destination / "Code"
        self._ensure_dir(code_dir)

        for project_dir in project_roots:
            target = safe_destination(code_dir, project_dir)

            if self.dry_run:
                logger.info(
                    "[DRY-RUN] Would move project: %s → %s", project_dir, target
                )
                if self._on_project_move:
                    self._on_project_move(project_dir, target)
                self.stats["moved"] += 1
                self.stats["projects"] += 1
                continue

            try:
                shutil.move(str(project_dir), str(target))
                logger.info("Moved project: %s → %s", project_dir, target)
                if self.journal:
                    self.journal.record_project(project_dir, target)
                if self._on_project_move:
                    self._on_project_move(project_dir, target)
                self.stats["moved"] += 1
                self.stats["projects"] += 1
            except PermissionError as exc:
                logger.error(
                    "Permission denied moving project %s: %s", project_dir, exc
                )
                if self._on_error:
                    self._on_error(project_dir, exc)
                self.stats["errors"] += 1
            except OSError as exc:
                logger.error(
                    "Error moving project %s: %s", project_dir, exc
                )
                if self._on_error:
                    self._on_error(project_dir, exc)
                self.stats["errors"] += 1

    def _ensure_dir(self, directory: Path) -> None:
        """Create *directory* (and parents) if it does not exist."""
        if directory.exists():
            return
        if self.dry_run:
            logger.info("[DRY-RUN] Would create directory: %s", directory)
            return
        directory.mkdir(parents=True, exist_ok=True)
        logger.info("Created directory: %s", directory)

    def _log_summary(self) -> None:
        """Print a human-readable run summary to the log."""
        s = self.stats
        logger.info("=" * 50)
        logger.info("Run complete%s", " (dry-run)" if self.dry_run else "")
        logger.info("  Files scanned   : %d", s["scanned"])
        logger.info("  Files moved     : %d", s["moved"])
        logger.info("  Projects moved  : %d", s["projects"])
        logger.info("  Duplicates found: %d", s["duplicates"])
        logger.info("  Files skipped   : %d", s["skipped"])
        logger.info("  Errors          : %d", s["errors"])
        logger.info("=" * 50)
