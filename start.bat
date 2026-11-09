@echo off
setlocal
set "START_PYTHON=%~dp0.venv\Scripts\python.exe"
if exist "%START_PYTHON%" goto run_app
set "START_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if exist "%START_PYTHON%" goto run_app
echo Virtual environment not found. Create .venv in the project or workspace first.
pause
exit /b 1

:run_app
pushd "%~dp0"
if errorlevel 1 (
    echo Unable to open the project directory.
    pause
    exit /b 1
)
"%START_PYTHON%" "%~dp0main.py" %*
set "START_EXIT_CODE=%ERRORLEVEL%"
popd
if not "%START_EXIT_CODE%"=="0" (
    echo.
    echo PipeTerminal-Free failed to start. Check the error above.
    pause
)
exit /b %START_EXIT_CODE%
