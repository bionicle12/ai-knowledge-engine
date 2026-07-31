@echo off
REM export.bat — double-click launcher: pack this base into a bundle (Windows).

setlocal

set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%scripts\kb_export.py" (
    set "PROJECT_ROOT=%SCRIPT_DIR%"
) else if exist "%SCRIPT_DIR%..\scripts\kb_export.py" (
    pushd "%SCRIPT_DIR%.."
    set "PROJECT_ROOT=%CD%\"
    popd
) else (
    echo ERROR: cannot find scripts\kb_export.py near this launcher
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
echo Export knowledge bundle
echo project: %PROJECT_ROOT%
echo --------------------------------------
echo.

python scripts\kb_export.py %*

echo.
echo Copy the bundle above to the other machine's sync\inbox\, then run its import launcher.
pause
endlocal
