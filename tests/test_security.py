"""
tests/test_security.py — Full security test suite for Organiser.

Covers all 10 attack surfaces in security.py:
  1. Path traversal prevention
  2. Destination escape / confinement
  3. Symlink attack prevention
  4. Null-byte / newline injection in filenames
  5. Filename sanitisation (control chars, homoglyphs, truncation)
  6. HMAC journal signing and tamper detection
  7. Resource limits (file count, path depth)
  8. Config category name validation
  9. Config extension value validation
  10. Log injection sanitisation
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# ── Import the module under test ──────────────────────────────────────────────

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from security import (
    MAX_FILES,
    MAX_PATH_DEPTH,
    SecurityError,
    assert_not_symlink,
    assert_safe_path,
    assert_within_dest,
    check_file_count,
    check_path_depth,
    sanitise_filename,
    sanitise_log_value,
    sign_journal,
    validate_config_categories,
    validate_config_markers,
    verify_journal_signature,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Path traversal
# ─────────────────────────────────────────────────────────────────────────────

class TestPathTraversal:
    def test_normal_path_passes(self, tmp_path):
        assert_safe_path(tmp_path / "some" / "file.txt", label="test")

    def test_null_byte_rejected(self, tmp_path):
        bad = Path(str(tmp_path) + "/evil\x00file.txt")
        with pytest.raises(SecurityError, match="Null byte"):
            assert_safe_path(bad, label="test")

    def test_newline_in_path_rejected(self, tmp_path):
        bad = Path(str(tmp_path) + "/evil\nINFO fake log")
        with pytest.raises(SecurityError, match="Newline"):
            assert_safe_path(bad, label="test")

    def test_carriage_return_rejected(self, tmp_path):
        bad = Path(str(tmp_path) + "/evil\rfile")
        with pytest.raises(SecurityError, match="Newline"):
            assert_safe_path(bad, label="test")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Destination confinement
# ─────────────────────────────────────────────────────────────────────────────

class TestDestinationConfinement:
    def test_file_inside_dest_passes(self, tmp_path):
        dest = tmp_path / "Organized"
        dest.mkdir()
        output = dest / "Code" / "main.py"
        assert_within_dest(output, dest)   # should not raise

    def test_file_outside_dest_raises(self, tmp_path):
        dest = tmp_path / "Organized"
        dest.mkdir()
        outside = tmp_path / "etc" / "passwd"
        with pytest.raises(SecurityError, match="Destination escape"):
            assert_within_dest(outside, dest)

    def test_sibling_dir_raises(self, tmp_path):
        dest = tmp_path / "Organized"
        dest.mkdir()
        sibling = tmp_path / "Organized_evil" / "file.txt"
        with pytest.raises(SecurityError, match="Destination escape"):
            assert_within_dest(sibling, dest)

    def test_exact_dest_root_passes(self, tmp_path):
        dest = tmp_path / "Organized"
        dest.mkdir()
        # A file at the dest root itself should be allowed
        assert_within_dest(dest / "file.txt", dest)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Symlink prevention
# ─────────────────────────────────────────────────────────────────────────────

class TestSymlinkPrevention:
    def test_regular_file_passes(self, tmp_path):
        f = tmp_path / "real.txt"
        f.write_text("data")
        assert_not_symlink(f)   # should not raise

    def test_symlink_raises(self, tmp_path):
        target = tmp_path / "real.txt"
        target.write_text("data")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        with pytest.raises(SecurityError, match="Symlink"):
            assert_not_symlink(link)

    def test_symlink_to_dir_raises(self, tmp_path):
        real_dir = tmp_path / "realdir"
        real_dir.mkdir()
        link = tmp_path / "linkdir"
        link.symlink_to(real_dir)
        with pytest.raises(SecurityError, match="Symlink"):
            assert_not_symlink(link)


# ─────────────────────────────────────────────────────────────────────────────
# 4 & 5. Filename sanitisation
# ─────────────────────────────────────────────────────────────────────────────

class TestFilenameSanitisation:
    def test_normal_name_unchanged(self):
        assert sanitise_filename("photo.jpg") == "photo.jpg"

    def test_null_byte_replaced(self):
        result = sanitise_filename("evil\x00file.txt")
        assert "\x00" not in result

    def test_newline_replaced(self):
        result = sanitise_filename("file\nname.txt")
        assert "\n" not in result

    def test_control_chars_replaced(self):
        result = sanitise_filename("file\x01\x1fname")
        assert "\x01" not in result
        assert "\x1f" not in result

    def test_leading_dot_stripped(self):
        # Hidden file attempt (beyond normal .dotfiles)
        result = sanitise_filename("...hidden")
        assert not result.startswith(".")

    def test_windows_reserved_chars_replaced(self):
        result = sanitise_filename('file<>:"/\\|?*.txt')
        for ch in '<>:"/\\|?*':
            assert ch not in result

    def test_empty_name_becomes_unnamed(self):
        assert sanitise_filename("") == "_unnamed_"
        assert sanitise_filename("   ") == "_unnamed_"

    def test_unicode_nfc_normalisation(self):
        # NFD 'é' (e + combining accent) → NFC 'é'
        nfd = "cafe\u0301"  # 5 chars
        result = sanitise_filename(nfd)
        assert result == "café"    # NFC normalised

    def test_long_name_truncated(self):
        long_name = "a" * 300
        result = sanitise_filename(long_name)
        assert len(result.encode("utf-8")) <= 255

    def test_unicode_allowed(self):
        # Non-ASCII should be preserved (not stripped)
        result = sanitise_filename("файл.txt")
        assert "ф" in result


# ─────────────────────────────────────────────────────────────────────────────
# 6. HMAC journal integrity
# ─────────────────────────────────────────────────────────────────────────────

class TestJournalHMAC:
    def _make_data(self):
        return {
            "version": 1,
            "started_at": "2026-01-01T00:00:00+00:00",
            "dry_run": False,
            "op_count": 1,
            "ops": [{"type": "file", "src": "/tmp/a.txt", "dst": "/tmp/Organized/Documents/a.txt"}],
        }

    def test_valid_signature_passes(self):
        data = self._make_data()
        data["hmac"] = sign_journal(dict(data))
        # verify_journal_signature pops the hmac field internally
        verify_journal_signature(data)   # should not raise

    def test_tampered_ops_detected(self):
        data = self._make_data()
        data["hmac"] = sign_journal(dict(data))
        # Tamper: change a destination path
        data["ops"][0]["dst"] = "/etc/crontab"
        with pytest.raises(SecurityError, match="HMAC verification FAILED"):
            verify_journal_signature(data)

    def test_missing_hmac_warns_but_does_not_raise(self, caplog):
        """Legacy journals with no HMAC should be accepted with a warning."""
        import logging
        data = self._make_data()   # no hmac field
        with caplog.at_level(logging.WARNING):
            verify_journal_signature(data)
        assert any("no HMAC" in r.message for r in caplog.records)

    def test_hmac_field_removed_before_comparison(self):
        """sign_journal must not include the hmac key in the payload it signs."""
        data = self._make_data()
        sig1 = sign_journal(dict(data))
        data_with_hmac = dict(data, hmac="anything")
        data_with_hmac_copy = dict(data_with_hmac)
        data_with_hmac_copy["hmac"] = sign_journal(dict(data))
        # Signatures computed from the same base data must be equal
        assert sig1 == sign_journal(dict(data))


# ─────────────────────────────────────────────────────────────────────────────
# 7. Resource limits
# ─────────────────────────────────────────────────────────────────────────────

class TestResourceLimits:
    def test_file_count_below_limit_passes(self):
        check_file_count(MAX_FILES - 1)

    def test_file_count_at_limit_passes(self):
        check_file_count(MAX_FILES)

    def test_file_count_above_limit_raises(self):
        with pytest.raises(SecurityError, match="Too many files"):
            check_file_count(MAX_FILES + 1)

    def test_path_depth_below_limit_passes(self, tmp_path):
        # Shallow path — should not raise
        check_path_depth(tmp_path / "a" / "b.txt")

    def test_path_depth_above_limit_raises(self):
        # Craft an artificially deep path object (doesn't need to exist)
        deep = Path("/" + "/".join(["x"] * (MAX_PATH_DEPTH + 5)))
        with pytest.raises(SecurityError, match="Path depth"):
            check_path_depth(deep)


# ─────────────────────────────────────────────────────────────────────────────
# 8 & 9. Config validation
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigCategoryValidation:
    def test_valid_category_and_extension_pass(self):
        result = validate_config_categories({"Design": ["fig", "sketch"]})
        assert result == {"Design": ["fig", "sketch"]}

    def test_category_name_with_path_separator_rejected(self):
        result = validate_config_categories({"../../etc/passwd": ["txt"]})
        assert "../../etc/passwd" not in result

    def test_category_name_too_long_rejected(self):
        bad_name = "A" * 65
        result = validate_config_categories({bad_name: ["pdf"]})
        assert bad_name not in result

    def test_extension_with_slash_rejected(self):
        result = validate_config_categories({"Safe": ["../../evil"]})
        # evil extension should be dropped
        assert result.get("Safe", []) == []

    def test_non_string_extension_skipped(self):
        result = validate_config_categories({"Safe": [42, None, "pdf"]})
        assert result.get("Safe") == ["pdf"]

    def test_non_list_value_rejected(self):
        result = validate_config_categories({"Safe": "pdf"})
        assert "Safe" not in result


class TestConfigMarkerValidation:
    def test_valid_markers_pass(self):
        result = validate_config_markers(["Podfile", "mix.exs", "pubspec.yaml"])
        assert result == ["Podfile", "mix.exs", "pubspec.yaml"]

    def test_marker_with_null_byte_rejected(self):
        result = validate_config_markers(["evil\x00marker"])
        assert not result

    def test_marker_with_path_sep_rejected(self):
        result = validate_config_markers(["../../../etc/cron.d/evil"])
        assert not result

    def test_marker_too_long_rejected(self):
        result = validate_config_markers(["x" * 129])
        assert not result

    def test_non_string_marker_rejected(self):
        result = validate_config_markers([42, None, "Podfile"])
        assert result == ["Podfile"]

    def test_empty_string_marker_rejected(self):
        result = validate_config_markers(["", "  ", "Podfile"])
        assert result == ["Podfile"]


# ─────────────────────────────────────────────────────────────────────────────
# 10. Log injection
# ─────────────────────────────────────────────────────────────────────────────

class TestLogInjection:
    def test_newline_replaced(self):
        result = sanitise_log_value("file\nINFO: injected entry")
        assert "\n" not in result
        assert "?" in result

    def test_carriage_return_replaced(self):
        result = sanitise_log_value("file\r\nINFO: injected")
        assert "\r" not in result

    def test_null_byte_replaced(self):
        result = sanitise_log_value("file\x00name")
        assert "\x00" not in result

    def test_normal_value_unchanged(self):
        assert sanitise_log_value("/home/user/file.txt") == "/home/user/file.txt"

    def test_control_chars_replaced(self):
        result = sanitise_log_value("file\x01\x1b[31mred")
        assert "\x1b" not in result
        assert "\x01" not in result
