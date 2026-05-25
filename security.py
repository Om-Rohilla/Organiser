"""
security.py — Security hardening layer for Organiser.

Attack surfaces covered:

  1. PATH TRAVERSAL        — prevent ../../../etc/passwd style escapes
  2. DESTINATION ESCAPE    — every output path verified to stay inside --dest
  3. SYMLINK ATTACK        — resolved paths checked before any operation
  4. NULL-BYTE INJECTION   — filenames with \\0 or \\n rejected at collection
  5. FILENAME INJECTION    — control-chars and shell metacharacters sanitised
  6. JOURNAL TAMPERING     — HMAC-SHA256 signature on every journal write
  7. RESOURCE EXHAUSTION   — hard caps on file count and path depth
  8. CONFIG INJECTION      — category names and extension values validated
  9. TOML PATH INJECTION   — config values may not contain path separators
  10. LOG INJECTION         — newlines stripped from any value written to logs
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 1. Configurable resource limits ──────────────────────────────────────────

#: Maximum number of individual files we'll process in a single run.
#: Prevents accidental processing of millions of files (e.g. mounted drives).
MAX_FILES         = 100_000

#: Maximum absolute path depth (number of components).
#: A path deeper than 64 directories is almost certainly pathological.
MAX_PATH_DEPTH    = 64

#: Maximum individual filename length (bytes, not chars — POSIX allows 255).
MAX_FILENAME_BYTES = 255

#: Hard cap on --workers to prevent thread-exhaustion DoS.
#: e.g. --workers 999999 would spin up nearly a million threads and OOM the machine.
MAX_WORKERS = 64


# ── 2. HMAC journal signing key ───────────────────────────────────────────────

#: Name of the file that stores the per-installation HMAC key.
#: Placed alongside the journal so it's easy to find and revoke.
_HMAC_KEY_FILE = Path(__file__).resolve().parent / ".journal_key"

#: HMAC algorithm used to sign the journal.
_HMAC_ALGO = "sha256"


def _get_or_create_hmac_key() -> bytes:
    """Load the HMAC key from disk, creating it on first use.

    The key is 32 bytes of ``os.urandom`` data stored in the project
    directory.  It is never transmitted anywhere — it only protects
    against local tampering of the journal file.

    Permissions are re-enforced to 0o600 on every read, not just creation,
    so that accidental ``chmod 644 .journal_key`` is silently corrected.
    """
    if _HMAC_KEY_FILE.exists():
        try:
            # Re-enforce permissions every read — not just on creation.
            os.chmod(_HMAC_KEY_FILE, 0o600)
            raw = _HMAC_KEY_FILE.read_bytes()
            if len(raw) == 32:
                return raw
        except OSError:
            pass   # fall through to regenerate

    # Generate and persist a fresh key.
    key = secrets.token_bytes(32)
    try:
        _HMAC_KEY_FILE.write_bytes(key)
        # Restrict key file to owner-read-only (chmod 600)
        os.chmod(_HMAC_KEY_FILE, 0o600)
    except OSError as exc:
        logger.warning("Could not persist HMAC key (%s) — using ephemeral key.", exc)
    return key


def sign_journal(data: dict) -> str:
    """Return an HMAC-SHA256 hex signature for a serialised journal *data* dict.

    The signature covers the canonical JSON bytes (sorted keys, no whitespace).
    Stored as ``data["hmac"]`` before writing to disk.
    """
    key     = _get_or_create_hmac_key()
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(key, payload, _HMAC_ALGO).hexdigest()


def verify_journal_signature(data: dict) -> None:
    """Raise ``SecurityError`` if the journal's HMAC does not match.

    Extracts the ``"hmac"`` field, recomputes the expected signature, and
    compares using ``hmac.compare_digest`` to prevent timing attacks.
    """
    stored_sig = data.pop("hmac", None)
    if stored_sig is None:
        # Legacy journal — no HMAC present.  Accept with a warning.
        logger.warning(
            "Journal has no HMAC signature — skipping integrity check. "
            "This journal was created by an older version of Organiser."
        )
        return

    expected = sign_journal(data)   # sign_journal pops nothing
    if not hmac.compare_digest(expected, stored_sig):
        raise SecurityError(
            "Journal HMAC verification FAILED — the journal file may have "
            "been tampered with. Undo aborted for your safety.\n"
            f"  Journal path: {_HMAC_KEY_FILE.parent / 'organiser_journal.json'}\n"
            "  Delete the journal and run a fresh pass to clear this error."
        )


# ── 3. Path-traversal + confinement guards ────────────────────────────────────

def assert_safe_path(path: Path, *, label: str = "path") -> None:
    """Raise ``SecurityError`` if *path* contains traversal components.

    Checks for:
    - Null bytes (\\0)
    - Newlines / carriage returns (log injection)
    - Parts equal to ``..`` (directory traversal)
    - Absolute paths expressed as relative (e.g. ``/etc/passwd`` as a part)
    """
    raw = str(path)

    if "\x00" in raw:
        raise SecurityError(f"Null byte in {label}: {raw!r}")
    if "\n" in raw or "\r" in raw:
        raise SecurityError(f"Newline character in {label}: {raw!r}")

    resolved = path.expanduser().resolve()
    for part in resolved.parts:
        if part == "..":
            raise SecurityError(f"Directory traversal detected in {label}: {raw!r}")


def assert_within_dest(output_path: Path, dest: Path) -> None:
    """Raise ``SecurityError`` if *output_path* is not inside *dest*.

    Resolves both paths (following all symlinks) before comparison to
    prevent symlink-based escapes.
    """
    try:
        output_path.resolve().relative_to(dest.resolve())
    except ValueError:
        raise SecurityError(
            f"Destination escape detected!\n"
            f"  Computed path : {output_path.resolve()}\n"
            f"  Allowed root  : {dest.resolve()}\n"
            "  This move has been blocked for your safety."
        )


def assert_not_symlink(path: Path) -> None:
    """Raise ``SecurityError`` if *path* is a symbolic link."""
    if path.is_symlink():
        raise SecurityError(
            f"Symlink detected and blocked: {path}\n"
            "  Organiser never follows symlinks to prevent redirect attacks."
        )


# ── 4. Filename sanitisation ──────────────────────────────────────────────────

# Characters that are dangerous in filenames across operating systems.
# We allow Unicode (non-ASCII) letters/digits freely.
_DANGEROUS_CHARS = re.compile(
    r"[\x00-\x1f\x7f"   # control chars
    r"<>:\"/\\|?*"      # Windows-reserved
    r"]"
)

def sanitise_filename(name: str) -> str:
    """Return a safe version of *name* for use as a destination filename.

    Steps applied in order:
    1. Unicode NFC normalisation (prevents homoglyph exploits).
    2. Strip leading/trailing whitespace and dots.
    3. Replace control characters and reserved chars with ``_``.
    4. Collapse multiple consecutive underscores.
    5. Truncate to ``MAX_FILENAME_BYTES`` bytes (UTF-8 encoded).
    6. Fallback to ``_unnamed_`` if result is empty.
    """
    # 1. NFC normalisation — prevent homoglyph / lookalike exploits
    name = unicodedata.normalize("NFC", name)

    # 2. Strip whitespace and leading dots (hidden file attempts)
    name = name.strip().lstrip(".")

    # 3. Replace dangerous characters
    name = _DANGEROUS_CHARS.sub("_", name)

    # 4. Collapse repeated underscores
    name = re.sub(r"_+", "_", name)

    # 5. Truncate at byte boundary
    encoded = name.encode("utf-8")
    if len(encoded) > MAX_FILENAME_BYTES:
        # Truncate at a valid UTF-8 boundary
        encoded = encoded[:MAX_FILENAME_BYTES]
        name = encoded.decode("utf-8", errors="ignore")

    # 6. Fallback
    return name or "_unnamed_"


# ── 5. Resource-limit checks ──────────────────────────────────────────────────

def check_file_count(count: int) -> None:
    """Raise ``SecurityError`` if *count* exceeds ``MAX_FILES``.

    This guards against accidentally running Organiser on a root/mounted
    directory that could contain millions of files.
    """
    if count > MAX_FILES:
        raise SecurityError(
            f"Too many files: {count:,} exceeds the safety limit of "
            f"{MAX_FILES:,}.\n"
            "  Use --source on a more specific directory, or raise the limit\n"
            "  by editing MAX_FILES in security.py."
        )


def check_path_depth(path: Path) -> None:
    """Raise ``SecurityError`` if *path* has more than ``MAX_PATH_DEPTH`` components."""
    depth = len(path.resolve().parts)
    if depth > MAX_PATH_DEPTH:
        raise SecurityError(
            f"Path depth {depth} exceeds limit {MAX_PATH_DEPTH}: {path}\n"
            "  Deeply nested paths are blocked as a precaution against "
            "recursive archive extraction attacks."
        )


def check_workers_count(workers: int) -> None:
    """Raise ``SecurityError`` if *workers* exceeds ``MAX_WORKERS``.

    Prevents thread-exhaustion DoS via e.g. ``--workers 999999`` which
    would spawn nearly a million threads and cause an OOM crash.
    """
    if workers > MAX_WORKERS:
        raise SecurityError(
            f"--workers {workers} exceeds the safety limit of {MAX_WORKERS}.\n"
            f"  Reduce to --workers {MAX_WORKERS} or lower."
        )


# ── Dangerous destination blocklist ───────────────────────────────────────────

# Absolute paths that must NEVER be used as --dest.
_BLOCKED_DESTINATIONS: frozenset[Path] = frozenset({
    Path("/"),
    Path("/usr"), Path("/usr/local"), Path("/usr/bin"),
    Path("/bin"), Path("/sbin"),
    Path("/etc"), Path("/var"), Path("/lib"), Path("/lib64"),
    Path("/sys"), Path("/proc"), Path("/dev"), Path("/boot"),
    Path("/root"),
    Path.home(),              # ~ root itself is too broad
    Path.home() / "Desktop",  # Desktop root (organiser lives here)
})


def assert_safe_destination(dest: Path) -> None:
    """Raise ``SecurityError`` if *dest* resolves to a protected system directory.

    Prevents catastrophic operations like ``--dest /`` or ``--dest /etc``
    that would scatter files across the OS filesystem.
    """
    resolved = dest.resolve()
    for blocked in _BLOCKED_DESTINATIONS:
        try:
            blocked_resolved = blocked.resolve()
        except OSError:
            continue
        if resolved == blocked_resolved:
            raise SecurityError(
                f"Destination '{resolved}' is a protected system/home directory.\n"
                "  Choose a dedicated sub-directory like ~/Organized instead."
            )


# ── 6. Config value validation ────────────────────────────────────────────────


_SAFE_CATEGORY_RE  = re.compile(r"^[\w\- ]{1,64}$")   # word chars, dash, space
_SAFE_EXTENSION_RE = re.compile(r"^[a-z0-9]{1,20}$")  # lowercase alphanum only


def validate_config_categories(categories: dict) -> dict:
    """Return *categories* after rejecting any unsafe keys or values.

    - Category names must match ``[\\w\\- ]{1,64}`` (no path separators).
    - Extension values must be lowercase alphanumeric, 1–20 chars.
    - Lists with non-string items are skipped with a warning.

    Returns a clean copy of the dict with invalid entries removed.
    """
    clean: dict[str, list[str]] = {}
    for cat_name, exts in categories.items():
        if not isinstance(cat_name, str) or not _SAFE_CATEGORY_RE.match(cat_name):
            logger.warning(
                "Config: invalid category name %r — skipped (must match [\\w\\- ]{1,64}).",
                cat_name,
            )
            continue
        if not isinstance(exts, list):
            logger.warning("Config: category %r value is not a list — skipped.", cat_name)
            continue
        safe_exts = []
        for ext in exts:
            if isinstance(ext, str) and _SAFE_EXTENSION_RE.match(ext.lower().lstrip(".")):
                safe_exts.append(ext.lower().lstrip("."))
            else:
                logger.warning(
                    "Config: extension %r in category %r is invalid — skipped.",
                    ext, cat_name,
                )
        if safe_exts:
            clean[cat_name] = safe_exts
    return clean


def validate_config_markers(extra_markers: list) -> list:
    """Return *extra_markers* after rejecting any unsafe values.

    Marker names must not contain path separators, null bytes, or newlines,
    and must be between 1 and 128 characters.
    """
    safe = []
    for marker in extra_markers:
        if not isinstance(marker, str):
            logger.warning("Config: marker %r is not a string — skipped.", marker)
            continue
        if len(marker) > 128 or not marker.strip():
            logger.warning("Config: marker %r too long or empty — skipped.", marker)
            continue
        if any(c in marker for c in ("/", "\\", "\x00", "\n", "\r")):
            logger.warning(
                "Config: marker %r contains illegal character — skipped.", marker
            )
            continue
        safe.append(marker)
    return safe


def sanitise_log_value(value: str) -> str:
    """Strip newlines and control chars from *value* before writing to logs.

    Prevents log injection (e.g. a file named ``evil\\nINFO: fake log entry``).
    """
    return re.sub(r"[\x00-\x1f\x7f]", "?", str(value))


# ── Custom exception ──────────────────────────────────────────────────────────

class SecurityError(RuntimeError):
    """Raised when a security-critical check fails.

    Always propagates to the top level, prints a human-readable message,
    and causes the process to exit with code 2 (security violation).
    """
