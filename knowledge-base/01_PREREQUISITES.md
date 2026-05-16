# 01 — Environment check

> The AI agent must run these checks **before** creating the knowledge base structure. If something is missing, give the user installation commands for their OS.
>
> **Reference template:** `knowledge-base/templates/requirements.txt`. The agent copies it into the deployed base root as `requirements.txt`.
> **After deployment** run `python3 scripts/kb_doctor.py` — it automatically checks the environment, dependencies, structure, and the spaCy model.

---

## Required components

| Tool | Minimum | Recommended | Why |
|------|--------:|------------:|-----|
| Node.js | `20.0.0+` | `22 LTS+` | Runs Repomix |
| Python | `3.11+` | `3.12+` | Local ingest pipeline |
| Git | any | latest | History, hooks |
| Repomix | any | latest | Knowledge indexing |
| IDE with AI | required | Codex / Cursor / JetBrains + AI | Review and base interaction |

## Verification

```bash
node --version      # >= 20.0.0
python3 --version   # >= 3.11
git --version
repomix --version
```

If `python` is not found, try `python3`.

## Installing Repomix

```bash
# Globally
npm install -g repomix

# Or zero-install
npx repomix@latest
```

## Python virtual environment

```bash
# Create venv at the base root
python3 -m venv .venv

# Activate
source .venv/bin/activate        # Linux/macOS
# .\.venv\Scripts\Activate.ps1   # Windows PowerShell

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

## requirements.txt

Copy `templates/requirements.txt` from this repo into the base root. Pinned to minor versions for reproducibility:

```text
pyyaml>=6.0,<7.0
python-slugify>=8.0,<9.0
python-frontmatter>=1.1,<2.0
python-docx>=1.1,<2.0
python-pptx>=0.6.23,<1.0
pypdf>=5.0,<6.0
pandas>=2.2,<3.0
openpyxl>=3.1,<4.0
spacy>=3.7,<4.0
rake-nltk>=1.0,<2.0
keybert>=0.8,<1.0
watchdog>=4.0,<5.0
```

Optional (OCR, images): uncomment `pytesseract` and `Pillow` inside `requirements.txt`.

## System utilities (optional)

| Utility | Why |
|---------|-----|
| `pandoc` | DOCX/HTML/MD conversions |
| `poppler-utils` / `pdftotext` | Text from PDF |
| `tesseract` | OCR for scans |
| `ffmpeg` | Audio from video for STT |

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

After installation, all four commands should succeed:

```bash
node --version && python3 --version && git --version && repomix --version
```

If PowerShell blocks the activate script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
