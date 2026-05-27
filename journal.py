"""
journal.py — Move journal for undo/rollback support.

Every file and project move is recorded to a JSON journal file before
execution.  After a run the user can pass ``--undo`` to reverse every
operation, restoring the source directory to its original state.

Journal format (v1)::

    {
      "version": 1,
      "organiser_version": "1.0",
      "started_at": "2026-05-24T16:00:00+00:00",
      "dry_run": false,
      "op_count": 42,
      "ops": [
        {"type": "file",    "src": "/path/to/src", "dst": "/path/to/dst"},
        {"type": "project", "src": "/path/to/dir", "dst": "/path/to/new"}
      ]
    }

The journal is written atomically (to a temp file then renamed) so an
interrupted run never leaves a half-written journal on disk.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from security import (
    SecurityError,
    sanitise_log_value,
    sign_journal,
    verify_journal_signature,
)

logger = logging.getLogger(__name__)

#: Default journal filename placed next to organizer.log
JOURNAL_FILENAME = "organiser_journal.json"

#: Increment this when the on-disk format changes incompatibly
_JOURNAL_VERSION = 1


class MoveJournal:
    """Record file/project moves and support atomic undo.

    Usage::

        journal = MoveJournal(Path("organiser_journal.json"))
        journal.record_file(src, dst)
        journal.record_project(src, dst)
        journal.save()          # writes atomically

        # Later, to undo:
        succeeded, failed = MoveJournal.undo(Path("organiser_journal.json"))
    """

    def __init__(self, path: Path, *, dry_run: bool = False) -> None:
        self._path   = path
        self._dry_run = dry_run
        self._ops: list[dict[str, str]] = []
        self._started_at = datetime.now(timezone.utc).isoformat()

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_file(self, src: Path, dst: Path) -> None:
        """Record a single-file move operation."""
        self._ops.append({"type": "file", "src": str(src), "dst": str(dst)})

    def record_project(self, src: Path, dst: Path) -> None:
        """Record a whole project-directory move operation."""
        self._ops.append({"type": "project", "src": str(src), "dst": str(dst)})

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        """Write the journal to disk atomically (temp-file + rename).

        The write is skipped when ``dry_run=True`` — nothing was actually
        moved, so there is nothing to undo.
        """
        if self._dry_run:
            logger.debug("Dry-run mode — journal not written.")
            return

        data = {
            "version":    _JOURNAL_VERSION,
            "started_at": self._started_at,
            "dry_run":    self._dry_run,
            "op_count":   len(self._ops),
            "ops":        self._ops,
        }
        # Sign the journal before writing so tampering can be detected on undo.
        data["hmac"] = sign_journal(dict(data))

        # Write to a temp file in the same directory, then rename atomically.
        parent = self._path.parent
        parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp_path, self._path)   # atomic on POSIX
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.info(
            "Journal saved to %s (%d operations)",
            sanitise_log_value(str(self._path)),
            len(self._ops),
        )

    # ── Undo ──────────────────────────────────────────────────────────────────

    @classmethod
    def undo(cls, path: Path) -> tuple[int, int]:
        """Reverse all operations recorded in the journal at *path*.

        Operations are replayed **in reverse order** (last move undone first)
        to handle cases where the same filename appears multiple times.

        Args:
            path: Path to a journal JSON file produced by :meth:`save`.

        Returns:
            ``(succeeded, failed)`` counts.
        """
        if not path.exists():
            raise FileNotFoundError(f"Journal not found: {path}")

        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        # Verify HMAC integrity before trusting any paths in the journal.
        verify_journal_signature(data)

        version = data.get("version", 0)
        if version != _JOURNAL_VERSION:
            raise ValueError(
                f"Unsupported journal version {version} "
                f"(expected {_JOURNAL_VERSION})"
            )

        ops: list[dict] = data.get("ops", [])
        succeeded = 0
        failed    = 0

        for op in reversed(ops):
            # Validate op structure before accessing keys — a corrupted or
            # partially written journal entry missing 'src' or 'dst' would
            # previously raise an unhandled KeyError, aborting the entire
            # undo run (all remaining ops are skipped).
            raw_src = op.get("src")
            raw_dst = op.get("dst")
            if not isinstance(raw_src, str) or not isinstance(raw_dst, str):
                logger.error(
                    "Undo skip — malformed journal op (missing/invalid src or dst): %s",
                    sanitise_log_value(str(op)),
                )
                failed += 1
                continue

            src = Path(raw_src)
            dst = Path(raw_dst)


            # Validate paths before moving (guard against tampered journal)
            try:
                from security import assert_safe_path
                assert_safe_path(src, label="journal src")
                assert_safe_path(dst, label="journal dst")
            except SecurityError as sec_exc:
                logger.error("Undo blocked — security violation: %s", sec_exc)
                failed += 1
                continue

            # Undo confinement: src and dst must share the same top-level
            # parent directory. This prevents a tampered journal from using
            # --undo to relocate arbitrary system files.
            # e.g. journal dst=/etc/crontab → undo would move it somewhere.
            if src.resolve().parts[:3] != dst.resolve().parts[:3]:
                logger.error(
                    "Undo blocked — src and dst are in different filesystem roots: "
                    "src=%s dst=%s", src, dst
                )
                failed += 1
                continue

            if not dst.exists():
                logger.warning(
                    "Undo skip — destination no longer exists: %s", dst
                )
                failed += 1
                continue

            # Ensure the original parent directory exists (might have been
            # created during the forward run and not cleaned up).
            src.parent.mkdir(parents=True, exist_ok=True)

            try:
                shutil.move(str(dst), str(src))
                logger.info(
                    "Undone: %s → %s",
                    sanitise_log_value(str(dst)),
                    sanitise_log_value(str(src)),
                )
                succeeded += 1
            except OSError as exc:
                logger.error(
                    "Undo failed for %s: %s",
                    sanitise_log_value(str(dst)), exc,
                )
                failed += 1

        return succeeded, failed

    # ── Convenience properties ─────────────────────────────────────────────────

    @property
    def op_count(self) -> int:
        """Total number of operations recorded so far."""
        return len(self._ops)

    @property
    def path(self) -> Path:
        """Filesystem path where the journal will be saved."""
        return self._path
