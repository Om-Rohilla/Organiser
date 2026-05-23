"""
tests/test_utils.py — Unit tests for utils.py

Run with:  pytest tests/
"""

import pytest
from pathlib import Path

from utils import get_category, safe_destination, format_size, UNKNOWN_CATEGORY


# ---------------------------------------------------------------------------
# get_category
# ---------------------------------------------------------------------------

class TestGetCategory:
    """Tests for get_category()."""

    @pytest.mark.parametrize(
        "filename, expected",
        [
            ("photo.jpg", "Images"),
            ("photo.JPG", "Images"),       # case-insensitive
            ("clip.MP4", "Videos"),
            ("song.flac", "Audio"),
            ("report.pdf", "Documents"),
            ("notes.txt", "Documents"),
            ("archive.zip", "Archives"),
            ("script.py", "Code"),
            ("app.exe", "Executables"),
            ("font.ttf", "Fonts"),
        ],
    )
    def test_known_extensions(self, filename: str, expected: str) -> None:
        assert get_category(Path(filename)) == expected

    def test_unknown_extension_returns_misc(self) -> None:
        assert get_category(Path("weirdfile.xyz123")) == UNKNOWN_CATEGORY

    def test_no_extension_returns_misc(self) -> None:
        assert get_category(Path("Makefile")) == UNKNOWN_CATEGORY

    def test_dotfile_returns_misc(self) -> None:
        # e.g. ".bashrc" — suffix is "" for these
        assert get_category(Path(".bashrc")) == UNKNOWN_CATEGORY


# ---------------------------------------------------------------------------
# safe_destination
# ---------------------------------------------------------------------------

class TestSafeDestination:
    """Tests for safe_destination()."""

    def test_returns_simple_path_when_free(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "Images"
        dest_dir.mkdir()
        source = Path("/some/source/photo.jpg")

        result = safe_destination(dest_dir, source)

        assert result == dest_dir / "photo.jpg"

    def test_increments_suffix_on_collision(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "Images"
        dest_dir.mkdir()

        # Create a file that would collide.
        (dest_dir / "photo.jpg").touch()

        source = Path("/other/source/photo.jpg")
        result = safe_destination(dest_dir, source)

        assert result == dest_dir / "photo_1.jpg"

    def test_increments_twice_on_two_collisions(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "Images"
        dest_dir.mkdir()

        (dest_dir / "photo.jpg").touch()
        (dest_dir / "photo_1.jpg").touch()

        source = Path("/other/source/photo.jpg")
        result = safe_destination(dest_dir, source)

        assert result == dest_dir / "photo_2.jpg"

    def test_no_extension_file(self, tmp_path: Path) -> None:
        dest_dir = tmp_path / "Misc"
        dest_dir.mkdir()
        source = Path("/some/Makefile")

        result = safe_destination(dest_dir, source)
        assert result == dest_dir / "Makefile"


# ---------------------------------------------------------------------------
# format_size
# ---------------------------------------------------------------------------

class TestFormatSize:
    """Tests for format_size()."""

    @pytest.mark.parametrize(
        "num_bytes, expected",
        [
            (0, "0.0 B"),
            (512, "512.0 B"),
            (1024, "1.0 KB"),
            (1536, "1.5 KB"),
            (1_048_576, "1.0 MB"),
            (1_073_741_824, "1.0 GB"),
        ],
    )
    def test_format(self, num_bytes: int, expected: str) -> None:
        assert format_size(num_bytes) == expected
