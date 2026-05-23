"""
utils.py — Shared helpers for file extension mapping and path utilities.

This module is intentionally small and pure (no side effects).
Everything here is easy to test in isolation.
"""

from pathlib import Path


# ---------------------------------------------------------------------------
# Extension → category mapping
# ---------------------------------------------------------------------------
# Add or edit entries here to change how files are sorted.
# Keys are lowercase extensions WITHOUT a leading dot.
# ---------------------------------------------------------------------------

EXTENSION_MAP: dict[str, str] = {
    # Images
    "jpg": "Images",
    "jpeg": "Images",
    "png": "Images",
    "gif": "Images",
    "bmp": "Images",
    "webp": "Images",
    "svg": "Images",
    "tiff": "Images",
    "ico": "Images",
    "heic": "Images",
    "raw": "Images",
    # Videos
    "mp4": "Videos",
    "mkv": "Videos",
    "avi": "Videos",
    "mov": "Videos",
    "wmv": "Videos",
    "flv": "Videos",
    "webm": "Videos",
    "m4v": "Videos",
    # Audio
    "mp3": "Audio",
    "wav": "Audio",
    "flac": "Audio",
    "aac": "Audio",
    "ogg": "Audio",
    "m4a": "Audio",
    "wma": "Audio",
    # Documents
    "pdf": "Documents",
    "doc": "Documents",
    "docx": "Documents",
    "xls": "Documents",
    "xlsx": "Documents",
    "ppt": "Documents",
    "pptx": "Documents",
    "odt": "Documents",
    "ods": "Documents",
    "txt": "Documents",
    "rtf": "Documents",
    "csv": "Documents",
    "md": "Documents",
    # Archives
    "zip": "Archives",
    "tar": "Archives",
    "gz": "Archives",
    "bz2": "Archives",
    "xz": "Archives",
    "rar": "Archives",
    "7z": "Archives",
    "dmg": "Archives",
    "iso": "Archives",
    # Code
    "py": "Code",
    "js": "Code",
    "ts": "Code",
    "html": "Code",
    "css": "Code",
    "json": "Code",
    "yaml": "Code",
    "yml": "Code",
    "toml": "Code",
    "sh": "Code",
    "bash": "Code",
    "c": "Code",
    "cpp": "Code",
    "h": "Code",
    "java": "Code",
    "go": "Code",
    "rs": "Code",
    "rb": "Code",
    "php": "Code",
    "sql": "Code",
    "xml": "Code",
    # Executables / binaries
    "exe": "Executables",
    "msi": "Executables",
    "apk": "Executables",
    "deb": "Executables",
    "rpm": "Executables",
    # Fonts
    "ttf": "Fonts",
    "otf": "Fonts",
    "woff": "Fonts",
    "woff2": "Fonts",
}

# Files with no recognized extension land here.
UNKNOWN_CATEGORY = "Misc"


def get_category(file_path: Path) -> str:
    """Return the category folder name for a given file.

    Args:
        file_path: Path to any file.

    Returns:
        A category string such as ``"Images"``, ``"Documents"``, etc.
        Falls back to ``UNKNOWN_CATEGORY`` when the extension is not mapped.
    """
    extension = file_path.suffix.lstrip(".").lower()
    return EXTENSION_MAP.get(extension, UNKNOWN_CATEGORY)


def safe_destination(destination_dir: Path, file_path: Path) -> Path:
    """Build the full destination path, avoiding silent overwrites.

    If ``destination_dir / file_path.name`` already exists, a numeric suffix
    is appended (e.g. ``report_1.pdf``, ``report_2.pdf``) until a free slot
    is found.

    Args:
        destination_dir: The folder where the file should land.
        file_path:        The source file being moved.

    Returns:
        A ``Path`` that does **not** yet exist on disk.
    """
    target = destination_dir / file_path.name
    if not target.exists():
        return target

    stem = file_path.stem
    suffix = file_path.suffix
    counter = 1

    while target.exists():
        target = destination_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    return target


def format_size(num_bytes: int) -> str:
    """Convert a byte count to a human-readable string (e.g. ``'4.2 MB'``).

    Args:
        num_bytes: Size in bytes.

    Returns:
        A formatted string with the appropriate unit.
    """
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024  # type: ignore[assignment]
    return f"{num_bytes:.1f} PB"
