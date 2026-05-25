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

    # ── Security: warn if config is writable by group/others ─────────────────
    try:
        mode = path.stat().st_mode & 0o777
        if mode & 0o022:   # group-write (0o020) or world-write (0o002)
            logger.warning(
                "Security warning: %s is writable by group/others (mode %04o). "
                "A malicious user could inject harmful categories or markers. "
                "Run: chmod 644 %s",
                path, mode, path,
            )
    except OSError:
        pass

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

    Values are validated through :func:`security.validate_config_categories`
    before being applied — malformed or injection-risk entries are dropped
    with a warning.
    """
    from security import validate_config_categories

    result = dict(extension_map)
    raw_categories = cfg.get("categories", {})
    safe_categories = validate_config_categories(raw_categories)

    for category, extensions in safe_categories.items():
        for ext in extensions:
            result[ext.lower().lstrip(".")] = category
    return result


def apply_config_to_marker_weights(
    cfg: dict,
    marker_weights: dict[str, int],
) -> dict[str, int]:
    """Merge extra project markers from config into *marker_weights*.

    Values are validated through :func:`security.validate_config_markers`
    before being applied.
    """
    from security import validate_config_markers

    result = dict(marker_weights)
    raw_markers = cfg.get("project_markers", {}).get("extra", [])
    for marker in validate_config_markers(raw_markers):
        result.setdefault(marker, 5)
    return result
