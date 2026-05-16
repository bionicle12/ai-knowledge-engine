@echo off
REM watcher-start.bat — double-click launcher for the file watcher (Windows).
REM Opens cmd.exe with the watcher running in the foreground.

setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

cls
echo Knowledge-base watcher
echo project: %CD%
echo Ctrl+C to stop
echo --------------------------------------
echo.

if exist "scripts\kb_watch.py" (
    python scripts\kb_watch.py
) else (
    echo ERROR: scripts\kb_watch.py not found
    pause
    exit /b 1
)

pause
endlocal
