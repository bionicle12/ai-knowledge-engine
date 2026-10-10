@echo off
rem Manual Windows entry point (cmd / double-click).
rem Git hooks do NOT need this file: on Windows git runs .sh hooks through
rem its bundled sh.exe. This wrapper finds that same bash to run the script.
setlocal
set "SCRIPT_DIR=%~dp0"

call :find_git_bash
if defined GIT_BASH (
    "%GIT_BASH%" "%SCRIPT_DIR%update-repomix-index.sh" %*
    goto :eof
)

rem Pack mode needs bash: a plain repomix run would write a full-project dump.
if exist "%SCRIPT_DIR%..\repomix.packs.json" (
    echo Repomix: Git Bash not found. Install Git for Windows, then re-run.
    exit /b 0
)

rem Legacy monolith, last resort: plain rebuild without freshness checks.
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
goto :eof

:find_git_bash
rem Git for Windows' bash first. A bare `where bash` can find the WSL
rem launcher (System32\bash.exe or WindowsApps\bash.exe), which would run the
rem script inside Linux with another PATH, node and repomix.
set "GIT_BASH="
for %%P in ("%ProgramFiles%\Git\bin\bash.exe" "%ProgramFiles(x86)%\Git\bin\bash.exe" "%LocalAppData%\Programs\Git\bin\bash.exe") do (
    if not defined GIT_BASH if exist "%%~P" set "GIT_BASH=%%~P"
)
if defined GIT_BASH goto :eof
for /f "delims=" %%G in ('where git 2^>nul') do (
    if not defined GIT_BASH if exist "%%~dpG..\bin\bash.exe" set "GIT_BASH=%%~dpG..\bin\bash.exe"
)
if defined GIT_BASH goto :eof
for /f "delims=" %%B in ('where bash 2^>nul') do (
    if not defined GIT_BASH (
        echo %%~B| findstr /i /c:"System32" /c:"WindowsApps" >nul || set "GIT_BASH=%%~B"
    )
)
goto :eof
