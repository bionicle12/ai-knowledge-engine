@echo off
REM import.bat — double-click launcher: merge every bundle sitting in
REM sync\inbox\ into this base (Windows).

setlocal

set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%scripts\kb_import.py" (
    set "PROJECT_ROOT=%SCRIPT_DIR%"
) else if exist "%SCRIPT_DIR%..\scripts\kb_import.py" (
    pushd "%SCRIPT_DIR%.."
    set "PROJECT_ROOT=%CD%\"
    popd
) else (
    echo ERROR: cannot find scripts\kb_import.py near this launcher
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
echo Import knowledge bundles from sync\inbox\
echo project: %PROJECT_ROOT%
echo --------------------------------------
echo.

python scripts\kb_import.py %*
set "CODE=%ERRORLEVEL%"

echo.
if "%CODE%"=="1" (
    echo Some pages changed on both machines - nothing was overwritten.
    echo Open the AI chat and send: !merge
)
if "%CODE%"=="0" (
    echo Merged cleanly. Send !merge in the AI chat so the agent cross-links the new knowledge.
)
pause
endlocal
