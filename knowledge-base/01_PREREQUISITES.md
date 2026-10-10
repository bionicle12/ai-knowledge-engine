# 01 — Environment check

> The AI agent must run these checks **before** creating the knowledge base structure. If something is missing, give the user installation commands for their OS.
>
> **Working directory:** the project root — the folder that holds `setup/` (the copied deployment kit). Every command below is written for it.
> **Reference templates:** `setup/templates/requirements*.txt`. The agent copies them into the deployed base root in `02_INIT.md` Phase 1.
> **After deployment** run `python3 scripts/kb_doctor.py` (or `bash shell/doctor.sh`) — it re-checks the environment, dependencies, structure, and the spaCy model. It **passes when it exits 0**; warnings alone do not fail it.

---

## Required components

| Tool | Minimum | Recommended | Why |
|------|--------:|------------:|-----|
| Node.js | `20.0.0+` | `22 LTS+` | Runs Repomix |
| Python | `3.11+` | `3.12+` | Local ingest pipeline |
| Git | any | latest | History, hooks |
| Repomix | `1.14.0` | the version in `index.repomix_version` | Knowledge indexing (global install or the `npx` fallback) |
| IDE with AI | required | Codex / Cursor / JetBrains + AI | Review and base interaction |

## Verification

```bash
node --version      # >= 20.0.0
python3 --version   # >= 3.11
git --version
repomix --version   # or, without a global install: npx --yes repomix@1.14.0 --version
```

If `python` is not found, try `python3` (Windows: `py -3`).

## Installing Repomix

```bash
# Globally, pinned to the version the base expects (index.repomix_version)
npm install -g repomix@1.14.0
```

Without a global `repomix`, `kb_reindex.py` runs `npx --yes repomix@<index.repomix_version>`
as long as `index.npx_fallback` is `true` (the default). That needs Node.js with
`npm` and network access on the first run. Set `index.npx_fallback: false` in
`kb.config.yml` to require the global install instead.

## Python virtual environment — at the project root

Create the venv at the **project root**, next to `setup/` — the folder that
becomes the base root after `finalize.sh`. Never create it inside
`knowledge-base/` or `setup/`: a virtualenv hard-codes its absolute path, so it
breaks when moved, and `finalize.sh` therefore never moves one.

```bash
# Linux / macOS — from the project root
python3 -m venv .venv
source .venv/bin/activate        # later `python3 ...` commands use the venv
python3 -m pip install --upgrade pip
python3 -m pip install -r setup/templates/requirements.txt
```

```powershell
# Windows PowerShell — from the project root
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r setup\templates\requirements.txt
```

The shell wrappers (`shell/*.sh`) and the double-click launchers do not need an
activated venv: they use `.venv/` at the base root, or — while the base is still
built in `knowledge-base/` next to `setup/` — the project-root `.venv/`, then fall
back to `python3` (the double-click launchers also accept the `venv/` of older
bases). Set `KB_PYTHON=/path/to/python` to force an interpreter.

**`ensurepip is not available`** (Debian / Ubuntu): the venv module is a separate
package. Install it, delete the half-created `.venv/`, and run `python3 -m venv .venv` again:

```bash
sudo apt install python3-venv     # or the versioned package the error names, e.g. python3.12-venv
```

**Moved or broken venv** (`.venv/bin/pip` fails, `VIRTUAL_ENV` points at an old
folder, `python3` is the system one after activation): do not repair it. Delete
`.venv/` and create it again with the commands above. `kb_doctor.py` warns about
such a venv.

**Base kept in a subfolder** (you skip `finalize.sh` and delete `setup/`): the
wrappers then only look at `<base>/.venv`, so create the venv inside the base
folder, or set `KB_PYTHON`.

## Requirements files

The agent copies all of them into the base root (02 Phase 1). Versions are
pinned inside the files — read them there rather than retyping a list.

| File | What it installs | When |
|------|------------------|------|
| `requirements.txt` | Core: YAML/frontmatter, document conversion (DOCX, PPTX, PDF, RTF, XLSX/CSV), spaCy + RAKE for NLP, the file watcher | Always |
| `requirements-nlp.txt` | KeyBERT keywords — pulls in PyTorch | Optional; without it ingest uses RAKE keywords |
| `requirements-media.txt` | Speech-to-text and OCR (see below) | Optional |
| `requirements-dev.txt` | pytest | Engine development only |

KeyBERT pulls PyTorch, and plain `pip` picks the CUDA build (gigabytes, many
minutes). Install the CPU-only wheel first:

```bash
python3 -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python3 -m pip install -r setup/templates/requirements-nlp.txt
```

### NLP data: spaCy model and NLTK

- spaCy needs a language model (`python3 -m spacy download ru_core_news_md`, or
  `en_core_web_md`) — see `12_NLP_PREPROCESS.md`.
- RAKE needs the NLTK `stopwords` and `punkt` data. Without them keyword
  extraction finds nothing:

  ```bash
  python3 -m nltk.downloader stopwords punkt punkt_tab
  ```

## Media: transcription (STT) & OCR — works out of the box, all platforms

Audio/video transcription and image OCR are **optional** and live in a separate
requirements file so the base install stays light. The defaults are chosen so
they work on macOS, Windows, and Linux **without any system tools** — in
particular, **no system `ffmpeg` is required**:

```bash
python3 -m pip install -r setup/templates/requirements-media.txt
```

This installs:

| Capability | Library | System dependency? |
|------------|---------|--------------------|
| Speech-to-text (audio + video) | `faster-whisper` | **None** — decodes audio via bundled PyAV |
| OCR (images / scans) | `rapidocr-onnxruntime` | **None** — ships its own ONNX models |

> **Why:** a Homebrew `ffmpeg` in `/opt/homebrew/bin` is often not on the PATH
> an IDE gives its child processes, so transcription failed with *"ffmpeg not
> found"*. `faster-whisper` needs no `ffmpeg`.

After installing, verify the backends are visible:

```bash
python3 setup/scripts/kb_stt.py --check
python3 setup/scripts/kb_ocr.py --check
```

`kb_doctor.py` reports STT/OCR/ffmpeg status too. See `15_MEDIA_PROCESSING.md` for the full contract.

## System utilities (truly optional)

These are only needed for specific alternative backends — the defaults above do
not require them.

| Utility | When you actually need it |
|---------|---------------------------|
| `pandoc` | Richer DOCX/HTML/MD conversions |
| `poppler-utils` / `pdftotext` | Alternative PDF text extraction |
| `tesseract` | The Tesseract OCR backend. RapidOCR (the default) reads only Chinese and English, so OCR of other text needs Tesseract with that language's data plus `pytesseract` (`requirements-media.txt`; see `15_MEDIA_PROCESSING.md`) |
| `ffmpeg` | Only if you choose the `openai-whisper` STT backend instead of faster-whisper |

### Ubuntu

```bash
sudo apt update
sudo apt install -y pandoc poppler-utils tesseract-ocr ffmpeg
```

### macOS

```bash
brew install pandoc poppler tesseract ffmpeg
```

### Windows

```powershell
winget install Gyan.FFmpeg
# Tesseract and Poppler — via Chocolatey/Scoop, add to PATH
```

If your package manager's Node.js is older than 20.0.0 — install via `nvm`, `fnm`, or NodeSource.

---

## Final check

After installation, all of these should succeed:

```bash
node --version && python3 --version && git --version
repomix --version || npx --yes repomix@1.14.0 --version
```

If PowerShell blocks the activate script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
