@echo off
REM reindex.bat — double-click launcher to run a manual reindex (Windows).

setlocal

set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%scripts\kb_ingest.py" (
    set "PROJECT_ROOT=%SCRIPT_DIR%"
) else if exist "%SCRIPT_DIR%..\scripts\kb_ingest.py" (
    pushd "%SCRIPT_DIR%.."
    set "PROJECT_ROOT=%CD%\"
    popd
) else (
    echo ERROR: cannot find scripts\kb_ingest.py near this launcher
    pause
    exit /b 1
)

cd /d "%PROJECT_ROOT%"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

cls
echo Manual reindex
echo project: %PROJECT_ROOT%
echo --------------------------------------
echo.

if exist "scripts\kb_reindex.py" (
    python scripts\kb_reindex.py
) else (
    python scripts\kb_ingest.py
    python scripts\kb_lint.py --quick
    where repomix >nul 2>nul && repomix
)

pause
endlocal
