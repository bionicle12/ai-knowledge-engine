@echo off
REM watcher-start.bat — double-click launcher for the file watcher (Windows).

setlocal

REM Resolve the project root: parent of this script's folder if shell/, else this folder.
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%scripts\kb_watch.py" (
    set "PROJECT_ROOT=%SCRIPT_DIR%"
) else if exist "%SCRIPT_DIR%..\scripts\kb_watch.py" (
    pushd "%SCRIPT_DIR%.."
    set "PROJECT_ROOT=%CD%\"
    popd
) else (
    echo ERROR: cannot find scripts\kb_watch.py near this launcher
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
echo Knowledge-base watcher
echo project: %PROJECT_ROOT%
echo Ctrl+C to stop
echo --------------------------------------
echo.

python scripts\kb_watch.py

pause
endlocal
