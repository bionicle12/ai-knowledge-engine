@echo off
rem Manual Windows entry point (cmd / double-click).
rem Git hooks do NOT need this file: on Windows git runs .sh hooks through
rem its bundled sh.exe. This wrapper finds that same bash to run the script.
setlocal
set "SCRIPT_DIR=%~dp0"

where bash >nul 2>nul
if %errorlevel% equ 0 (
    bash "%SCRIPT_DIR%update-repomix-index.sh" %*
    goto :eof
)

if exist "%ProgramFiles%\Git\bin\bash.exe" (
    "%ProgramFiles%\Git\bin\bash.exe" "%SCRIPT_DIR%update-repomix-index.sh" %*
    goto :eof
)

rem Last resort: plain rebuild without freshness checks / pack status.
where repomix >nul 2>nul
if %errorlevel% equ 0 (
    echo Repomix: Git Bash not found, running plain repomix build...
    pushd "%SCRIPT_DIR%.."
    repomix
    popd
) else (
    echo Repomix: neither Git Bash nor repomix found. Install Git for Windows and: npm install -g repomix
    exit /b 0
)
