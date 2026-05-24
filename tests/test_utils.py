"""
tests/test_utils.py — Unit tests for utils.py

Run with:  pytest tests/
"""

import pytest
from pathlib import Path

from utils import get_category, safe_destination, format_size, UNKNOWN_CATEGORY, is_code_project, project_confidence, PROJECT_THRESHOLD


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


# ---------------------------------------------------------------------------
# is_code_project / project_confidence
# ---------------------------------------------------------------------------

class TestIsCodeProject:
    """Tests for the confidence-based project detection."""

    def test_git_folder_is_definitive_project(self, tmp_path: Path) -> None:
        """A .git directory alone scores 10, well above the threshold."""
        project = tmp_path / "my-repo"
        project.mkdir()
        (project / ".git").mkdir()
        assert is_code_project(project) is True

    def test_package_json_is_project(self, tmp_path: Path) -> None:
        project = tmp_path / "frontend"
        project.mkdir()
        (project / "package.json").write_text("{}")
        assert is_code_project(project) is True

    def test_lone_requirements_txt_is_not_project(self, tmp_path: Path) -> None:
        """requirements.txt alone scores 3 — below the threshold of 5."""
        folder = tmp_path / "stuff"
        folder.mkdir()
        (folder / "requirements.txt").write_text("rich")
        assert is_code_project(folder) is False

    def test_requirements_plus_setup_py_is_project(self, tmp_path: Path) -> None:
        """requirements.txt (3) + setup.py (5) = 8 — above threshold."""
        folder = tmp_path / "lib"
        folder.mkdir()
        (folder / "requirements.txt").write_text("rich")
        (folder / "setup.py").write_text("from setuptools import setup")
        assert is_code_project(folder) is True

    def test_empty_folder_is_not_project(self, tmp_path: Path) -> None:
        folder = tmp_path / "empty"
        folder.mkdir()
        assert is_code_project(folder) is False

    def test_random_files_are_not_project(self, tmp_path: Path) -> None:
        folder = tmp_path / "photos"
        folder.mkdir()
        (folder / "holiday.jpg").write_bytes(b"img")
        (folder / "notes.txt").write_text("hi")
        assert is_code_project(folder) is False

    def test_project_confidence_returns_int(self, tmp_path: Path) -> None:
        folder = tmp_path / "proj"
        folder.mkdir()
        (folder / "Cargo.toml").write_text("[package]")
        score = project_confidence(folder)
        assert isinstance(score, int)
        assert score >= PROJECT_THRESHOLD

    def test_dotnet_sln_suffix_is_project(self, tmp_path: Path) -> None:
        """A .sln file should score via _SUFFIX_WEIGHTS."""
        folder = tmp_path / "dotnet"
        folder.mkdir()
        (folder / "MyApp.sln").write_text("")
        assert is_code_project(folder) is True
