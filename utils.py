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
    "jsx": "Code",      # React / JSX
    "tsx": "Code",      # React + TypeScript
    "vue": "Code",      # Vue.js
    "svelte": "Code",   # Svelte
    "html": "Code",
    "css": "Code",
    "scss": "Code",     # Sass
    "sass": "Code",
    "less": "Code",
    "json": "Code",
    "yaml": "Code",
    "yml": "Code",
    "toml": "Code",
    "sh": "Code",
    "bash": "Code",
    "zsh": "Code",
    "fish": "Code",
    "c": "Code",
    "cpp": "Code",
    "cc": "Code",
    "h": "Code",
    "hpp": "Code",
    "java": "Code",
    "kt": "Code",       # Kotlin
    "kts": "Code",
    "swift": "Code",    # Swift
    "dart": "Code",     # Flutter / Dart
    "go": "Code",
    "rs": "Code",
    "rb": "Code",
    "php": "Code",
    "sql": "Code",
    "xml": "Code",
    "gitignore": "Code",    # common config files
    "env": "Code",
    "lock": "Code",
    "dockerfile": "Code",
    "makefile": "Code",
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


# ---------------------------------------------------------------------------
# Code-project detection — confidence scoring
# ---------------------------------------------------------------------------

# Each marker file/directory is assigned a weight.  A folder must reach
# PROJECT_THRESHOLD to be treated as a project root (moved wholesale).
#
# Using weights instead of a simple boolean prevents false positives:
# e.g. a random folder containing only a loose "requirements.txt" scores 3
# — below the threshold — and its files are sorted individually instead.
MARKER_WEIGHTS: dict[str, int] = {
    # Version control — definitive proof
    ".git":               10,
    # Node / JavaScript
    "package.json":        8,
    "yarn.lock":           5,
    "package-lock.json":   4,
    # Python
    "pyproject.toml":      7,
    "Pipfile":             6,
    "setup.py":            5,
    "setup.cfg":           4,
    "requirements.txt":    3,   # alone is NOT enough (common loose file)
    # Rust
    "Cargo.toml":          8,
    # Go
    "go.mod":              8,
    # Java
    "pom.xml":             8,
    "build.gradle":        7,
    "build.gradle.kts":    7,
    "gradlew":             5,
    "mvnw":                5,
    # C / C++
    "CMakeLists.txt":      6,
    "Makefile":            3,   # alone is not enough (many non-code Makefiles)
    # Ruby
    "Gemfile":             7,
    # PHP
    "composer.json":       7,
    # Docker / Infra
    "Dockerfile":          5,
    "docker-compose.yml":  4,
    "docker-compose.yaml": 4,
}

#: Minimum cumulative score to classify a folder as a code project.
PROJECT_THRESHOLD: int = 5

# File *suffix* weights (extension without dot).
_SUFFIX_WEIGHTS: dict[str, int] = {
    "sln":       8,   # .NET solution
    "csproj":    7,   # .NET project
    "xcodeproj": 7,   # Xcode project
    "podspec":   6,   # CocoaPods
    "cabal":     6,   # Haskell
    "gemspec":   6,   # Ruby gem spec
}


def project_confidence(folder: Path) -> int:
    """Return the confidence score for *folder* being a code project root.

    Only direct children are inspected (no deep scan).  Scores accumulate
    up to ``PROJECT_THRESHOLD``; iteration stops as soon as the threshold
    is reached for performance on large directories.

    Args:
        folder: Directory to inspect.

    Returns:
        An integer score.  A score ≥ ``PROJECT_THRESHOLD`` means the folder
        should be treated as a code project.
    """
    score = 0
    try:
        for item in folder.iterdir():
            score += MARKER_WEIGHTS.get(item.name, 0)
            score += _SUFFIX_WEIGHTS.get(item.suffix.lstrip(".").lower(), 0)
            if score >= PROJECT_THRESHOLD:
                return score        # early exit — no need to scan further
    except PermissionError:
        pass
    return score


def is_code_project(folder: Path) -> bool:
    """Return ``True`` if *folder* looks like a code project root.

    Delegates to :func:`project_confidence`.  A folder qualifies when its
    combined marker score reaches :data:`PROJECT_THRESHOLD`.

    Args:
        folder: Directory to inspect.

    Returns:
        ``True`` if the confidence score meets the threshold.
    """
    return project_confidence(folder) >= PROJECT_THRESHOLD


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

    The loop is capped at ``MAX_COLLISION_ATTEMPTS`` (99 999) to prevent an
    infinite loop when the filesystem is full or a degenerate directory
    contains an extremely large number of name-collisions.

    Args:
        destination_dir: The folder where the file should land.
        file_path:        The source file being moved.

    Returns:
        A ``Path`` that does **not** yet exist on disk.

    Raises:
        RuntimeError: If more than ``MAX_COLLISION_ATTEMPTS`` collisions occur,
            indicating a pathological filesystem state.
    """
    #: Hard limit on rename attempts to prevent infinite loops.
    MAX_COLLISION_ATTEMPTS = 99_999

    stem   = file_path.stem
    suffix = file_path.suffix
    target = destination_dir / file_path.name
    counter = 1

    while target.exists():
        if counter > MAX_COLLISION_ATTEMPTS:
            raise RuntimeError(
                f"safe_destination: exceeded {MAX_COLLISION_ATTEMPTS} collision "
                f"attempts for '{file_path.name}' in '{destination_dir}'. "
                "The destination directory may be in a degenerate state."
            )
        target = destination_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    return target


def format_size(num_bytes: int) -> str:
    """Convert a byte count to a human-readable string (e.g. ``'4.2 MB'``).

    Args:
        num_bytes: Size in bytes (non-negative integer).

    Returns:
        A formatted string with the appropriate unit.
    """
    value: float = float(num_bytes)   # explicit float avoids int /= type error
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"
