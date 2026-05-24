"""
tests/test_organizer.py — Integration-style tests for organizer.py

All tests use tmp_path (pytest built-in fixture) so nothing touches
your real filesystem.

Run with:  pytest tests/
"""

from pathlib import Path

import pytest

from organizer import FileOrganizer, compute_md5, compute_hash


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_file(directory: Path, name: str, content: bytes = b"hello") -> Path:
    """Create a file with the given name and content inside *directory*."""
    path = directory / name
    path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# compute_md5
# ---------------------------------------------------------------------------

class TestComputeMd5:
    """Unit tests for the free function compute_md5()."""

    def test_returns_correct_hash(self, tmp_path: Path) -> None:
        """Hash must be deterministic — same content → same digest."""
        content = b"deterministic content"
        f1 = make_file(tmp_path, "sample1.txt", content)
        f2 = make_file(tmp_path, "sample2.txt", content)

        _, digest1 = compute_hash(f1)
        _, digest2 = compute_hash(f2)

        # Both files have the same bytes → digests must match
        assert digest1 is not None
        assert digest1 == digest2

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        ghost = tmp_path / "ghost.txt"  # does not exist
        _, digest = compute_hash(ghost)
        assert digest is None

    def test_different_content_gives_different_hash(self, tmp_path: Path) -> None:
        a = make_file(tmp_path, "a.txt", b"aaa")
        b = make_file(tmp_path, "b.txt", b"bbb")

        _, digest_a = compute_hash(a)
        _, digest_b = compute_hash(b)

        assert digest_a != digest_b


# ---------------------------------------------------------------------------
# FileOrganizer — dry run
# ---------------------------------------------------------------------------

class TestFileOrganizerDryRun:
    """Verify that dry-run mode never touches the filesystem."""

    def test_no_files_moved_in_dry_run(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        make_file(source, "photo.jpg")
        make_file(source, "notes.txt")

        organizer = FileOrganizer(source, dest, dry_run=True)
        organizer.run()

        # Files must still be in source.
        assert (source / "photo.jpg").exists()
        assert (source / "notes.txt").exists()

        # No category folders should have been created.
        assert not list(dest.iterdir())

    def test_stats_still_count_in_dry_run(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        make_file(source, "a.jpg", b"unique-image-content")
        make_file(source, "b.pdf", b"unique-document-content")

        organizer = FileOrganizer(source, dest, dry_run=True)
        organizer.run()

        assert organizer.stats["scanned"] == 2
        assert organizer.stats["moved"] == 2


# ---------------------------------------------------------------------------
# FileOrganizer — real moves
# ---------------------------------------------------------------------------

class TestFileOrganizerRealMoves:
    """Verify files land in the correct category folders."""

    def test_image_goes_to_images_folder(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"

        make_file(source, "sunset.jpg")

        organizer = FileOrganizer(source, dest, dry_run=False)
        organizer.run()

        assert (dest / "Images" / "sunset.jpg").exists()
        assert not (source / "sunset.jpg").exists()

    def test_multiple_categories_created(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"

        make_file(source, "clip.mp4", b"video-bytes")
        make_file(source, "report.pdf", b"document-bytes")
        make_file(source, "app.py", b"python-bytes")

        organizer = FileOrganizer(source, dest, dry_run=False)
        organizer.run()

        assert (dest / "Videos" / "clip.mp4").exists()
        assert (dest / "Documents" / "report.pdf").exists()
        assert (dest / "Code" / "app.py").exists()

    def test_unknown_extension_goes_to_misc(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"

        make_file(source, "datafile.xyz999")

        organizer = FileOrganizer(source, dest, dry_run=False)
        organizer.run()

        assert (dest / "Misc" / "datafile.xyz999").exists()

    def test_filename_collision_is_resolved(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"

        # Two files with the same name but different content.
        sub_a = source / "a"
        sub_a.mkdir()
        sub_b = source / "b"
        sub_b.mkdir()

        make_file(sub_a, "photo.jpg", b"content-a")
        make_file(sub_b, "photo.jpg", b"content-b")

        organizer = FileOrganizer(source, dest, dry_run=False)
        organizer.run()

        images_dir = dest / "Images"
        moved_files = {f.name for f in images_dir.iterdir()}

        # Both files must end up in Images/ without one overwriting the other.
        assert "photo.jpg" in moved_files
        assert "photo_1.jpg" in moved_files

    def test_stats_reflect_actual_moves(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"

        make_file(source, "a.jpg", b"image-one")
        make_file(source, "b.jpg", b"image-two")
        make_file(source, "c.pdf", b"document-one")

        organizer = FileOrganizer(source, dest, dry_run=False)
        organizer.run()

        assert organizer.stats["scanned"] == 3
        assert organizer.stats["moved"] == 3
        assert organizer.stats["errors"] == 0


# ---------------------------------------------------------------------------
# FileOrganizer — duplicate detection
# ---------------------------------------------------------------------------

class TestDuplicateDetection:
    """Verify that content-identical files are detected and only one is kept."""

    def test_duplicate_is_skipped(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"

        identical_content = b"i am a duplicate"

        sub_a = source / "a"
        sub_a.mkdir()
        sub_b = source / "b"
        sub_b.mkdir()

        make_file(sub_a, "file.txt", identical_content)
        make_file(sub_b, "file_copy.txt", identical_content)

        organizer = FileOrganizer(source, dest, dry_run=False)
        organizer.run()

        assert organizer.stats["duplicates"] == 1
        assert organizer.stats["skipped"] == 1

        # Only one file should exist in the destination.
        moved = list((dest / "Documents").iterdir())
        assert len(moved) == 1

    def test_unique_files_are_not_flagged(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"

        make_file(source, "a.txt", b"unique content A")
        make_file(source, "b.txt", b"unique content B")

        organizer = FileOrganizer(source, dest, dry_run=False)
        organizer.run()

        assert organizer.stats["duplicates"] == 0
        assert organizer.stats["moved"] == 2
