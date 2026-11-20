@echo off
setlocal
cd /d "%~dp0"

set "CONDA_ROOT=C:\Users\Prism\anaconda3"
set "CONDA_ENV=C:\Users\Prism\anaconda3\envs\DeadletterMail"

if exist "%CONDA_ROOT%\Scripts\activate.bat" (
    call "%CONDA_ROOT%\Scripts\activate.bat" "%CONDA_ENV%"
) else (
    set "PATH=%CONDA_ENV%;%CONDA_ENV%\Library\bin;%CONDA_ENV%\Scripts;%PATH%"
)

if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
        call :load_env_var "%%~A" "%%~B"
    )
) else (
    echo [WARNING] .env file not found in "%~dp0". Relying on existing environment variables.
)

if not defined DISCORD_BOT_TOKEN if defined DISCORD_TOKEN (
    set "DISCORD_BOT_TOKEN=%DISCORD_TOKEN%"
)

if not defined DISCORD_BOT_TOKEN (
    echo [ERROR] DISCORD_BOT_TOKEN is not set in .env or environment.
    echo Add a line like: DISCORD_BOT_TOKEN=your_bot_token_here
    pause
    exit /b 1
)

"%CONDA_ENV%\python.exe" manage.py run_discord_bot %*
pause
goto :eof

:load_env_var
set "ENV_KEY=%~1"
set "ENV_VAL=%~2"
for /f "tokens=1 delims= " %%K in ("%ENV_KEY%") do set "ENV_KEY=%%K"
if "%ENV_KEY%"=="" goto :eof
if "%ENV_KEY:~0,1%"=="#" goto :eof
set "%ENV_KEY%=%ENV_VAL%"
goto :eof
