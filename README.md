<h1 align="center">🗂️ File Organizer</h1>

<p align="center">
  <b>A production-grade CLI tool that sorts, deduplicates, and logs your files — blazing fast with multiprocessing.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/stdlib%20only-no%20deps-brightgreen?style=for-the-badge" />
  <img src="https://img.shields.io/badge/tests-35%20passing-success?style=for-the-badge&logo=pytest" />
  <img src="https://img.shields.io/badge/license-MIT-orange?style=for-the-badge" />
</p>

---

## 📌 What It Does

You run it like this:

```bash
python main.py --source ~/Downloads --dest ~/Organized
```

And it:

1. 🔍 **Scans** your source folder recursively
2. 📂 **Sorts** every file into a category sub-folder (`Images/`, `Documents/`, `Code/`, etc.)
3. 🔑 **Detects duplicates** by comparing actual file *content* via MD5 hash — not just names
4. ⚡ **Hashes in parallel** using all available CPU cores (`multiprocessing`)
5. 📝 **Logs everything** to both the console and `organizer.log`
6. 🧪 **Dry-run mode** — preview all changes before anything is moved

---

## ✨ Features

| Feature | Detail |
|---|---|
| **Smart sorting** | 50+ extensions mapped across 8 categories |
| **Duplicate detection** | MD5 content hashing — finds identical files regardless of name |
| **Multiprocessing** | Hashing runs across all CPU cores in parallel |
| **Dry-run mode** | Preview what would happen — zero files moved |
| **Safe renames** | Name collisions auto-resolved: `photo.jpg` → `photo_1.jpg` |
| **Structured logging** | Every action logged to `organizer.log` + console |
| **100% stdlib** | No third-party runtime dependencies |
| **35 tests** | Full unit + integration test suite with `pytest` |

---

## 📁 Project Structure

```
organiser/
│
├── main.py              # ← Entry point: argparse + logging setup
├── organizer.py         # ← Core logic: scan → hash → deduplicate → move
├── utils.py             # ← Pure helpers: extension map, path utilities
│
├── tests/
│   ├── __init__.py
│   ├── test_utils.py    # ← 23 unit tests
│   └── test_organizer.py# ← 12 integration tests
│
├── requirements.txt     # ← pytest only
├── .gitignore
└── README.md
```

---

## ⚙️ Setup

```bash
# 1. Clone the repo
git clone https://github.com/Om-Rohilla/Organiser.git
cd Organiser

# 2. (Recommended) Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install test dependency
pip install -r requirements.txt
```

> **Note:** No extra packages are needed to *run* the organizer — it uses Python's standard library only.

---

## 🚀 Usage

### Basic — sort and move files

```bash
python main.py --source ~/Downloads --dest ~/Organized
```

### Dry-run — preview without moving anything

```bash
python main.py --source ~/Downloads --dest ~/Organized --dry-run
```

### Verbose — show debug output

```bash
python main.py --source ~/Downloads --dest ~/Organized --verbose
```

### Custom worker count

```bash
python main.py --source ~/Downloads --dest ~/Organized --workers 4
```

---

## 🏳️ CLI Flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--source DIR` | `Path` | **required** | Directory to scan (recursive) |
| `--dest DIR` | `Path` | **required** | Root folder for sorted output |
| `--dry-run` | flag | `off` | Preview mode — nothing is moved |
| `--workers N` | `int` | `cpu_count` | Parallel hashing processes |
| `--verbose` | flag | `off` | Show DEBUG messages on console |

---

## 📦 Output Categories

| Folder | Extensions |
|---|---|
| `Images/` | jpg, jpeg, png, gif, bmp, webp, svg, tiff, ico, heic, raw |
| `Videos/` | mp4, mkv, avi, mov, wmv, flv, webm, m4v |
| `Audio/` | mp3, wav, flac, aac, ogg, m4a, wma |
| `Documents/` | pdf, doc, docx, xls, xlsx, ppt, pptx, txt, csv, md, rtf |
| `Archives/` | zip, tar, gz, bz2, xz, rar, 7z, dmg, iso |
| `Code/` | py, js, ts, html, css, json, yaml, sh, c, cpp, java, go, rs… |
| `Executables/` | exe, msi, apk, deb, rpm |
| `Fonts/` | ttf, otf, woff, woff2 |
| `Misc/` | anything else |

---

## 🖥️ Example Output

```
2026-05-23 20:00:00  INFO      File Organizer started.
2026-05-23 20:00:00  INFO      Source      : /home/user/Downloads
2026-05-23 20:00:00  INFO      Destination : /home/user/Organized
2026-05-23 20:00:00  INFO      Dry-run     : False
2026-05-23 20:00:00  INFO      Found 142 file(s) to process.
2026-05-23 20:00:01  INFO      Hashing 142 file(s) using multiprocessing …
2026-05-23 20:00:01  WARNING   Duplicate content detected (MD5: d41d8c…). Keeping: photo.jpg
2026-05-23 20:00:01  WARNING     └─ duplicate (will be skipped): photo_copy.jpg
2026-05-23 20:00:02  INFO      Moved: /home/user/Downloads/photo.jpg → /home/user/Organized/Images/photo.jpg
2026-05-23 20:00:03  INFO      ==================================================
2026-05-23 20:00:03  INFO      Run complete
2026-05-23 20:00:03  INFO        Files scanned   : 142
2026-05-23 20:00:03  INFO        Files moved     : 139
2026-05-23 20:00:03  INFO        Duplicates found: 3
2026-05-23 20:00:03  INFO        Files skipped   : 3
2026-05-23 20:00:03  INFO        Errors          : 0
2026-05-23 20:00:03  INFO      ==================================================
```

---

## 🧪 Running Tests

```bash
# Run all 35 tests with verbose output
pytest tests/ -v
```

Expected result:

```
tests/test_utils.py::TestGetCategory::test_known_extensions[photo.jpg-Images] PASSED
tests/test_utils.py::TestGetCategory::test_no_extension_returns_misc PASSED
tests/test_organizer.py::TestFileOrganizerDryRun::test_no_files_moved_in_dry_run PASSED
tests/test_organizer.py::TestDuplicateDetection::test_duplicate_is_skipped PASSED
...
35 passed in 1.23s
```

---

## 🎓 What You Learn From This Project

| Concept | Module / Tool |
|---|---|
| File system traversal | `pathlib.Path.rglob()` |
| Cryptographic hashing | `hashlib.md5()` |
| Parallel CPU work | `concurrent.futures.ProcessPoolExecutor` |
| Production logging | `logging` (dual handler: console + file) |
| Safe file operations | `shutil.move()` + custom collision resolver |
| Robust error handling | `try / except OSError, PermissionError` |
| CLI argument parsing | `argparse` |
| Unit & integration testing | `pytest`, `tmp_path` fixture |

---

## 📄 License

This project is open source and available under the [MIT License](LICENSE).

---

<p align="center">Built with ❤️ and Python's standard library — no pip install drama.</p>
