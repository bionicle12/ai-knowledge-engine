@echo off
REM reindex.bat — double-click launcher to run a manual reindex (Windows).

setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

cls
echo Manual reindex
echo project: %CD%
echo --------------------------------------
echo.

if exist "scripts\kb_ingest.py" (
    python scripts\kb_ingest.py
    if exist "scripts\kb_lint.py" (
        python scripts\kb_lint.py --quick
    )
    where repomix >nul 2>nul
    if %errorlevel% equ 0 repomix
) else (
    echo ERROR: scripts\kb_ingest.py not found
)

pause
endlocal
