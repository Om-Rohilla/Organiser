"""
tests/test_journal.py — Unit tests for journal.py (undo/rollback)

Run with:  pytest tests/
"""

import json
from pathlib import Path

import pytest

from journal import MoveJournal, JOURNAL_FILENAME


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_file(directory: Path, name: str, content: bytes = b"data") -> Path:
    path = directory / name
    path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# MoveJournal — recording
# ---------------------------------------------------------------------------

class TestMoveJournalRecording:

    def test_record_file_adds_op(self, tmp_path: Path) -> None:
        j = MoveJournal(tmp_path / "journal.json")
        j.record_file(Path("/src/a.txt"), Path("/dst/a.txt"))
        assert j.op_count == 1

    def test_record_project_adds_op(self, tmp_path: Path) -> None:
        j = MoveJournal(tmp_path / "journal.json")
        j.record_project(Path("/src/proj"), Path("/dst/Code/proj"))
        assert j.op_count == 1

    def test_multiple_ops_counted(self, tmp_path: Path) -> None:
        j = MoveJournal(tmp_path / "journal.json")
        for i in range(5):
            j.record_file(Path(f"/src/file{i}.txt"), Path(f"/dst/file{i}.txt"))
        assert j.op_count == 5


# ---------------------------------------------------------------------------
# MoveJournal — save
# ---------------------------------------------------------------------------

class TestMoveJournalSave:

    def test_save_creates_json_file(self, tmp_path: Path) -> None:
        path = tmp_path / "journal.json"
        j = MoveJournal(path)
        j.record_file(Path("/a"), Path("/b"))
        j.save()
        assert path.exists()

    def test_saved_json_has_correct_structure(self, tmp_path: Path) -> None:
        path = tmp_path / "journal.json"
        j = MoveJournal(path)
        j.record_file(Path("/src/x.txt"), Path("/dst/x.txt"))
        j.save()

        data = json.loads(path.read_text())
        assert data["version"] == 1
        assert data["op_count"] == 1
        assert len(data["ops"]) == 1
        assert data["ops"][0]["type"] == "file"

    def test_dry_run_does_not_save(self, tmp_path: Path) -> None:
        path = tmp_path / "journal.json"
        j = MoveJournal(path, dry_run=True)
        j.record_file(Path("/a"), Path("/b"))
        j.save()
        assert not path.exists()


# ---------------------------------------------------------------------------
# MoveJournal — undo
# ---------------------------------------------------------------------------

class TestMoveJournalUndo:

    def test_undo_restores_file(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        dst_dir = tmp_path / "dest"
        dst_dir.mkdir()

        # Simulate a file that was moved
        original = src_dir / "photo.jpg"
        moved    = dst_dir / "photo.jpg"
        moved.write_bytes(b"img")

        path = tmp_path / "journal.json"
        j = MoveJournal(path)
        j.record_file(original, moved)
        j.save()

        ok, fail = MoveJournal.undo(path)

        assert ok == 1
        assert fail == 0
        assert original.exists()
        assert not moved.exists()

    def test_undo_reverses_in_order(self, tmp_path: Path) -> None:
        """Last move should be undone first."""
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        (dst / "a.txt").write_bytes(b"a")
        (dst / "b.txt").write_bytes(b"b")

        path = tmp_path / "journal.json"
        j = MoveJournal(path)
        j.record_file(src / "a.txt", dst / "a.txt")
        j.record_file(src / "b.txt", dst / "b.txt")
        j.save()

        ok, fail = MoveJournal.undo(path)
        assert ok == 2
        assert fail == 0
        assert (src / "a.txt").exists()
        assert (src / "b.txt").exists()

    def test_undo_skips_missing_destination(self, tmp_path: Path) -> None:
        """If the moved file is gone, undo should count it as failed."""
        path = tmp_path / "journal.json"
        j = MoveJournal(path)
        j.record_file(tmp_path / "src" / "x.txt", tmp_path / "dst" / "x.txt")
        j.save()

        ok, fail = MoveJournal.undo(path)
        assert ok == 0
        assert fail == 1

    def test_undo_raises_on_missing_journal(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            MoveJournal.undo(tmp_path / "nonexistent.json")
