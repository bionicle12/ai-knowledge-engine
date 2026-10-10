@echo off
REM import.bat - double-click launcher: merge every bundle sitting in
REM sync\inbox\ into this base (Windows).
REM Works from shell\ and from the base root (where finalize.sh promotes it).

setlocal

REM Project root: this folder, or its parent while the launcher sits in shell\.
REM No %CD% inside a parenthesized block: cmd expands it before pushd runs.
set "PROJECT_ROOT="
if exist "%~dp0scripts\kb_import.py" set "PROJECT_ROOT=%~dp0"
if not defined PROJECT_ROOT for %%I in ("%~dp0..") do if exist "%%~fI\scripts\kb_import.py" set "PROJECT_ROOT=%%~fI\"
if not defined PROJECT_ROOT (
    echo ERROR: cannot find scripts\kb_import.py near this launcher
    pause
    exit /b 1
)
cd /d "%PROJECT_ROOT%"

REM Python, same order as shell/_kbpy.sh: %KB_PYTHON%, the base's .venv, the
REM project .venv while the base still sits next to setup\ (before
REM finalize.sh), then the legacy venv\ of older bases, then the py launcher,
REM then python on PATH.
set "PY=%KB_PYTHON%"
set "PYARGS="
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "..\setup\scripts\kb_common.py" if exist "..\.venv\Scripts\python.exe" set "PY=..\.venv\Scripts\python.exe"
if not defined PY if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if not defined PY where py >nul 2>nul && set "PY=py"
if not defined PY set "PY=python"
if "%PY%"=="py" set "PYARGS=-3"

cls
echo Import knowledge bundles from sync\inbox\
echo project: %PROJECT_ROOT%
echo --------------------------------------
echo.

"%PY%" %PYARGS% scripts\kb_import.py %*
set "CODE=%ERRORLEVEL%"

echo.
if "%CODE%"=="1" echo Some pages changed on both machines - nothing was overwritten.
if "%CODE%"=="1" echo Open the AI chat and send: !merge
if "%CODE%"=="0" echo Merged cleanly. Send !merge in the AI chat so the agent cross-links the new knowledge.
if not "%CODE%"=="0" if not "%CODE%"=="1" echo Import failed with exit code %CODE% - see the messages above.
pause
endlocal & exit /b %CODE%
