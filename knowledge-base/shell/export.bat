@echo off
REM export.bat - double-click launcher: pack this base into a bundle (Windows).
REM Works from shell\ and from the base root (where finalize.sh promotes it).

setlocal

REM Project root: this folder, or its parent while the launcher sits in shell\.
REM No %CD% inside a parenthesized block: cmd expands it before pushd runs.
set "PROJECT_ROOT="
if exist "%~dp0scripts\kb_export.py" set "PROJECT_ROOT=%~dp0"
if not defined PROJECT_ROOT for %%I in ("%~dp0..") do if exist "%%~fI\scripts\kb_export.py" set "PROJECT_ROOT=%%~fI\"
if not defined PROJECT_ROOT (
    echo ERROR: cannot find scripts\kb_export.py near this launcher
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
echo Export knowledge bundle
echo project: %PROJECT_ROOT%
echo --------------------------------------
echo.

"%PY%" %PYARGS% scripts\kb_export.py %*
set "CODE=%ERRORLEVEL%"

echo.
if "%CODE%"=="0" echo Copy the bundle above to the other machine's sync\inbox\, then run its import launcher.
if not "%CODE%"=="0" echo Export failed with exit code %CODE% - see the messages above.
pause
endlocal & exit /b %CODE%
