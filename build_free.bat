@echo off
setlocal
set "BUILD_HELPER=%~dp0packaging\build.py"
set "BUILD_PYTHON=%PIPETERMINAL_BUILD_PYTHON%"
if defined BUILD_PYTHON goto run_python
if exist "%~dp0.venv\Scripts\python.exe" (
    set "BUILD_PYTHON=%~dp0.venv\Scripts\python.exe"
    goto run_python
)
if exist "%~dp0..\.venv\Scripts\python.exe" (
    set "BUILD_PYTHON=%~dp0..\.venv\Scripts\python.exe"
    goto run_python
)
where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%BUILD_HELPER%" --name PipeTerminal-Free
    goto finished
)
set "BUILD_PYTHON=python"

:run_python
"%BUILD_PYTHON%" "%BUILD_HELPER%" --name PipeTerminal-Free

:finished
if errorlevel 1 goto failed
echo.
echo Free portable package is ready. See the output path above.
pause
exit /b 0

:failed
echo.
echo Build failed. Check the error above.
pause
exit /b 1
