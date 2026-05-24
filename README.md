<h1 align="center">🗂️ Organiser</h1>

<p align="center">
  <b>A production-grade CLI tool that scans, sorts, deduplicates, and safely organises your files — blazing fast with parallel I/O.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/xxHash-5--10x_faster-blueviolet?style=for-the-badge" />
  <img src="https://img.shields.io/badge/tests-53_passing-success?style=for-the-badge&logo=pytest" />
  <img src="https://img.shields.io/badge/safety-undo_%2B_backup-orange?style=for-the-badge" />
  <img src="https://img.shields.io/badge/license-MIT-lightgrey?style=for-the-badge" />
</p>

---

## 📌 What It Does

```bash
.venv/bin/python3 main.py --source ~/Downloads --dest ~/Organized
```

Organiser:

1. 🔍 **Scans** your source folder recursively, detecting real files and complete code projects
2. 🧠 **Identifies code projects** using a confidence-weighted scoring system — moves the whole folder, not individual files
3. 🔑 **Deduplicates** by hashing actual file content (xxHash → MD5 fallback) — not just filenames
4. ⚡ **Processes in parallel** — hashing and moves run across all CPU cores via `ThreadPoolExecutor`
5. 📂 **Sorts** into clean category sub-folders (`Images/`, `Documents/`, `Code/`, etc.)
6. 📓 **Journals every move** — so you can undo the entire run instantly
7. 🧪 **Dry-run mode** — preview every change before anything is touched
8. ⏪ **Undo any run** — reverses all moves in one command, restoring files to exact original locations

---

## ✨ Feature Matrix

| Feature | Detail |
|---|---|
| **Smart project detection** | Confidence-weighted scoring (`package.json`, `Cargo.toml`, `.git`, etc.) — avoids false positives |
| **Dependency-dir exclusion** | Never recurses into `node_modules`, `.venv`, `.git`, `dist`, `build`, and 17 other noise dirs |
| **xxHash deduplication** | 5–10× faster than MD5; falls back to MD5 automatically if xxhash is not installed |
| **Parallel I/O** | `ThreadPoolExecutor` for concurrent file hashing and moves |
| **`--dry-run` mode** | See exactly what will happen — zero files moved |
| **`--undo` rollback** | JSON journal records every move; one command reverses the entire run |
| **`--fresh` safe reset** | Instead of `rm -rf`, moves existing dest to a timestamped backup before a clean run |
| **Existing-dest warning** | Warns if destination is non-empty before running |
| **Safe renames** | Name collisions auto-resolved: `photo.jpg` → `photo_1.jpg` |
| **User config** | Extend categories and project markers via `organiser.toml` — no code editing needed |
| **53 tests** | Unit, integration, concurrency, and rollback test suites |
| **Rich UI** | Beautiful terminal output with progress bars and summary tables |

---

## 📁 Project Structure

```
organiser/
│
├── main.py              # Entry point: argparse, --fresh, --undo, safety checks
├── organizer.py         # Core engine: scan → hash → deduplicate → parallel move → journal
├── utils.py             # Helpers: extension map, confidence-scored project detection
├── journal.py           # Atomic JSON journal for undo / rollback
├── ui.py                # Rich-based terminal UI (banner, progress, summary table)
├── protocols.py         # Type-safe UI callback protocols (IDE-friendly)
├── config.py            # organiser.toml loader (user-defined categories + markers)
│
├── organiser.toml       # ← Edit this to customise without touching code
│
├── tests/
│   ├── test_utils.py          # Extension map + project confidence tests
│   ├── test_organizer.py      # Integration tests: move, dedup, dry-run, parallel
│   └── test_journal.py        # Undo / rollback tests
│
├── requirements.txt     # rich, xxhash, pytest
├── .gitignore
└── README.md
```

---

## ⚙️ Setup

```bash
# 1. Clone the repo
git clone https://github.com/Om-Rohilla/Organiser.git
cd Organiser

# 2. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## 🚀 Usage

### Basic — sort and move files

```bash
.venv/bin/python3 main.py --source ~/Downloads --dest ~/Organized
```

### Dry-run — preview without moving anything

```bash
.venv/bin/python3 main.py --source ~/Downloads --dest ~/Organized --dry-run
```

### Fresh run — safely back up existing destination first

```bash
# Moves ~/Organized → ~/Organized_backup_2026-05-24_22-00-00, then starts clean
.venv/bin/python3 main.py --source ~/Downloads --dest ~/Organized --fresh
```

### Undo — reverse the last run completely

```bash
.venv/bin/python3 main.py --undo
```

> Every file is moved back to its **exact original path**. Runs in reverse order to handle nested moves correctly.

### Custom worker count

```bash
.venv/bin/python3 main.py --source ~/Downloads --dest ~/Organized --workers 4
```

---

## 🏳️ CLI Reference

| Flag | Default | Description |
|---|---|---|
| `--source DIR` | **required** | Directory to scan (recursive). Not needed with `--undo`. |
| `--dest DIR` | **required** | Root folder for sorted output. Not needed with `--undo`. |
| `--dry-run` | `off` | Preview all changes — nothing is moved |
| `--fresh` | `off` | Safely back up existing `--dest` before starting |
| `--undo` | `off` | Reverse the last run using the saved journal |
| `--workers N` | all cores | Parallel workers for hashing and moves |
| `--verbose` | `off` | Print DEBUG-level messages to console |

---

## 🧠 How Project Detection Works

Organiser moves entire code project folders as a single unit — not their individual files. It uses **confidence-weighted scoring** to avoid false positives:

| Marker file | Weight |
|---|---|
| `.git/` directory | 4 |
| `package.json` | 3 |
| `Cargo.toml` | 3 |
| `pyproject.toml` | 3 |
| `go.mod` | 3 |
| `requirements.txt` | 2 |
| `Makefile` | 1 |
| `README.md` | 1 |

A folder must reach a **cumulative score ≥ 5** to be treated as a project. This prevents lone `Makefile` or `README.md` files from triggering false project detection.

---

## 🚫 Excluded Directories

Organiser **never** recurses into these to avoid processing thousands of dependency files:

```
node_modules  .npm  .yarn          # JavaScript
.venv  venv  env  __pycache__      # Python
.mypy_cache  .pytest_cache
dist  build  out  target           # Build output
.next  .nuxt  .svelte-kit  _site
.gradle
.git  .hg  .svn                    # Version control
.idea  .vscode                     # IDE
```

---

## 📦 Output Categories

| Folder | Extensions |
|---|---|
| `Images/` | jpg, jpeg, png, gif, bmp, webp, svg, tiff, ico, heic, raw |
| `Videos/` | mp4, mkv, avi, mov, wmv, flv, webm, m4v |
| `Audio/` | mp3, wav, flac, aac, ogg, m4a, wma |
| `Documents/` | pdf, doc, docx, xls, xlsx, ppt, pptx, txt, csv, md, rtf |
| `Archives/` | zip, tar, gz, bz2, xz, rar, 7z, dmg, iso |
| `Code/` | py, js, ts, jsx, tsx, vue, svelte, html, css, scss, json, yaml, sh, c, cpp, java, go, rs, kt, swift, dart… |
| `Executables/` | exe, msi, apk, deb, rpm |
| `Fonts/` | ttf, otf, woff, woff2 |
| `Misc/` | anything else |

> **Tip:** Add your own categories in `organiser.toml` — no code changes needed.

---

## ⚙️ organiser.toml (User Config)

```toml
# organiser.toml — placed in the project root
# Extend categories with your own extensions

[categories]
"Design" = ["fig", "sketch", "xd", "psd", "ai"]
"Data"   = ["csv", "parquet", "feather", "pkl"]

[project_markers]
"composer.json" = 3   # PHP projects
"mix.exs"       = 3   # Elixir projects
```

---

## 🖥️ Example Output

```
╭─────────────────────────────────────────────────────────╮
│                  🗂️  File Organizer                     │
│             Scan · Sort · Deduplicate · Log             │
╰─────────────────────────────────────────────────────────╯

╭──────────────────── ⚙  Configuration ─────────────────────╮
│  📁  Source         /home/user/Desktop                    │
│  📂  Destination    /home/user/Organized                  │
│  🔍  Mode           LIVE — files will be moved            │
│  ⚙️   Workers       auto (all CPU cores)                  │
╰────────────────────────────────────────────────────────────╯

  Found 86 file(s) + 13 code project(s) to process.

  🔑  Computing hashes… ━━━━━━━━━━━━━━ 86/86 100% 0:00:00
       ⊗  DUPE   tailwind.config.js

      ✔  README.md                   →  Documents/README.md
      ✔  cost_comparison.png         →  Images/cost_comparison.png
      ✔  generate_ieee_paper.py      →  Code/generate_ieee_paper.py
      📁 PROJ  recall                →  Code/recall
      📁 PROJ  campus-event-hub      →  Code/campus-event-hub
      ...

  ↩  To undo this run: python main.py --undo

╭──────────────── ✔  Run Complete ───────────────╮
│   Files scanned      │   99   │                │
│   Files moved        │   97   │                │
│   Projects moved     │   13   │                │
│   Duplicates found   │    1   │   !            │
│   Errors             │    0   │   ✓            │
╰────────────────────────────────────────────────╯
```

---

## 🧪 Running Tests

```bash
# Run all 53 tests
.venv/bin/pytest tests/ -v

# Run a specific suite
.venv/bin/pytest tests/test_journal.py -v      # undo/rollback tests
.venv/bin/pytest tests/test_organizer.py -v    # integration tests
.venv/bin/pytest tests/test_utils.py -v        # unit tests
```

Expected:
```
53 passed in 0.63s
```

---

## 🛡️ Safety Design

Organiser is built around a **zero data-loss** philosophy:

| Risk | Protection |
|---|---|
| Accidental overwrite | Files are never overwritten — collisions get `_1`, `_2` suffixes |
| Duplicate files moved | Content-hash deduplication skips exact duplicates |
| Regret after a run | `--undo` reverses all moves using a JSON journal |
| Starting over dangerously | `--fresh` backs up existing dest instead of deleting it |
| Moving into source itself | Self-move guard prevents organiser from eating its own directory |
| Infinite symlink loops | All symlinks are skipped |
| Dependency folder pollution | 22 built-in excluded directory names |

---

## 🎓 Key Technical Concepts

| Concept | Where |
|---|---|
| File system traversal | `pathlib.Path.rglob()` with exclusion pruning |
| Content hashing | `xxhash.xxh64()` with `hashlib.md5()` fallback |
| Parallel I/O | `concurrent.futures.ThreadPoolExecutor` |
| Atomic journaling | JSON-based move log with reverse-order undo |
| Confidence scoring | Weighted marker detection for project roots |
| Type-safe callbacks | `typing.Protocol` in `protocols.py` |
| User configuration | `tomllib` / `tomli` for `organiser.toml` |
| Rich terminal UI | `rich` — progress bars, tables, styled output |
| CLI argument parsing | `argparse` with graceful validation |
| Testing | `pytest` with `tmp_path` fixture — 53 tests |

---

## 📄 License

MIT License — open source, free to use, modify, and distribute.

---

<p align="center">
  Built with ❤️ by <a href="https://github.com/Om-Rohilla">Om Rohilla</a>
  <br/>
  <i>Scan · Sort · Deduplicate · Undo · Never Lose a File</i>
</p>
