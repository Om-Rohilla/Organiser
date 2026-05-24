"""
protocols.py — Structural-typing Protocols for all UI callback signatures.

Using ``typing.Protocol`` instead of bare ``Callable`` gives:
  - Full IDE autocompletion for callback parameters
  - Static type-checking via mypy / pyright
  - Zero runtime overhead (duck-typed, not enforced at runtime)

Import these in organizer.py for type annotations, and in main.py when
wiring the actual Rich-based implementations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class OnHashed(Protocol):
    """Called once after each individual file has been MD5/xxHash-hashed."""

    def __call__(self) -> None:
        ...


@runtime_checkable
class OnMove(Protocol):
    """Called once a file has been (or in dry-run, *would* be) moved.

    Args:
        src: Original file path.
        dst: Destination path the file was moved to.
    """

    def __call__(self, src: Path, dst: Path) -> None:
        ...


@runtime_checkable
class OnProjectMove(Protocol):
    """Called after a whole code-project directory is moved into ``Code/``.

    Args:
        project_dir: The original project root directory.
        target:      Where the project landed (``dest/Code/<name>``).
    """

    def __call__(self, project_dir: Path, target: Path) -> None:
        ...


@runtime_checkable
class OnDuplicate(Protocol):
    """Called when a file is identified as a duplicate and will be skipped.

    Args:
        path: The duplicate file that will *not* be moved.
    """

    def __call__(self, path: Path) -> None:
        ...


@runtime_checkable
class OnError(Protocol):
    """Called when a move operation fails with an exception.

    Args:
        path: The file that could not be moved.
        exc:  The exception that was raised.
    """

    def __call__(self, path: Path, exc: Exception) -> None:
        ...
