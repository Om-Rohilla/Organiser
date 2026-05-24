"""
config.py — Optional TOML-based user configuration for Organiser.

If an ``organiser.toml`` is found (checked in priority order), its values
override the built-in defaults.  The file is **completely optional** — the
tool works identically without it.

Search order (first found wins):
  1. ``./organiser.toml``                         ← project-local
  2. ``~/.config/organiser/organiser.toml``       ← user-wide

Example ``organiser.toml``::

    [behavior]
    dry_run = false
    workers = 4            # 0 = auto (all CPU cores)

    [categories]
    # Extend or override the built-in extension map.
    # Keys are lowercase extensions WITHOUT a leading dot.
    CAD    = ["dwg", "dxf", "step", "iges"]
    eBooks = ["epub", "mobi", "azw3"]
    RAW    = ["arw", "cr2", "nef", "orf"]

    [project_markers]
    # Additional filenames to score as project markers (weight = 5 each).
    extra = ["Podfile", "pubspec.yaml", "mix.exs", "rebar.config"]

Uses ``tomllib`` (Python 3.11+ stdlib) with a graceful fallback message
when running on Python < 3.11 without the ``tomli`` back-port.
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── TOML loader (stdlib 3.11+, or ask user to pip install tomli) ──────────────

try:
    if sys.version_info >= (3, 11):
        import tomllib          # stdlib
    else:
        import tomli as tomllib  # type: ignore[no-redef]
    _TOML_AVAILABLE = True
except ImportError:
    _TOML_AVAILABLE = False
    tomllib = None  # type: ignore[assignment]

# ── Config search paths (first found wins) ────────────────────────────────────

_CONFIG_CANDIDATES: list[Path] = [
    Path("organiser.toml"),
    Path.home() / ".config" / "organiser" / "organiser.toml",
]

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULTS: dict = {
    "behavior": {
        "dry_run": False,
        "workers": None,   # None → auto (all CPU cores)
    },
    "categories": {},          # merged ON TOP of utils.EXTENSION_MAP
    "project_markers": {
        "extra": [],           # additional marker names, weight 5 each
    },
}


# ── Public API ─────────────────────────────────────────────────────────────────

def find_config_file() -> Path | None:
    """Return the first ``organiser.toml`` found on the search path, or None."""
    for candidate in _CONFIG_CANDIDATES:
        if candidate.exists():
            return candidate.resolve()
    return None


def load_config() -> dict:
    """Load and return the merged configuration dictionary.

    Returns ``_DEFAULTS`` unchanged when:
      - no ``organiser.toml`` is found, OR
      - ``tomllib`` is not available (Python < 3.11 without ``tomli``).

    The returned dict has the same top-level keys as ``_DEFAULTS``.
    """
    import copy
    cfg = copy.deepcopy(_DEFAULTS)

    path = find_config_file()
    if path is None:
        return cfg

    if not _TOML_AVAILABLE:
        logger.warning(
            "organiser.toml found at %s but tomllib is not available. "
            "Run 'pip install tomli' on Python < 3.11 to enable config loading.",
            path,
        )
        return cfg

    try:
        with open(path, "rb") as fh:
            user_cfg = tomllib.load(fh)
    except Exception as exc:
        logger.warning("Could not parse %s: %s — using defaults.", path, exc)
        return cfg

    # Shallow-merge each section
    for section in ("behavior", "categories", "project_markers"):
        if section in user_cfg:
            cfg[section].update(user_cfg[section])

    logger.info("Loaded config from %s", path)
    return cfg


def apply_config_to_extension_map(
    cfg: dict,
    extension_map: dict[str, str],
) -> dict[str, str]:
    """Merge user-defined ``[categories]`` into *extension_map*.

    The ``[categories]`` section maps category names to lists of extensions::

        [categories]
        CAD = ["dwg", "dxf"]

    Each extension (lowercase, no dot) is added/overwritten in the map.

    Args:
        cfg:           Config dict returned by :func:`load_config`.
        extension_map: The base ``EXTENSION_MAP`` from ``utils.py``.

    Returns:
        A new dict that is *extension_map* plus any user overrides.
    """
    result = dict(extension_map)
    for category, extensions in cfg.get("categories", {}).items():
        for ext in extensions:
            result[ext.lower().lstrip(".")] = category
    return result


def apply_config_to_marker_weights(
    cfg: dict,
    marker_weights: dict[str, int],
) -> dict[str, int]:
    """Merge extra project markers from config into *marker_weights*.

    The ``[project_markers]`` section supports an ``extra`` list::

        [project_markers]
        extra = ["Podfile", "pubspec.yaml"]

    Each extra marker is given a weight of 5 (strong signal, but not
    as definitive as ``.git`` which scores 10).

    Args:
        cfg:            Config dict returned by :func:`load_config`.
        marker_weights: The base ``MARKER_WEIGHTS`` from ``utils.py``.

    Returns:
        A new dict with extra markers appended.
    """
    result = dict(marker_weights)
    for marker in cfg.get("project_markers", {}).get("extra", []):
        result.setdefault(marker, 5)
    return result
