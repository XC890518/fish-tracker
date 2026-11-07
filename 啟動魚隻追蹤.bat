@echo off
setlocal
cd /d "%~dp0"
if exist "%USERPROFILE%\anaconda3\python.exe" (
    set "PATH=%USERPROFILE%\anaconda3;%USERPROFILE%\anaconda3\Library\bin;%PATH%"
    "%USERPROFILE%\anaconda3\python.exe" "%~dp0fish_tracker.py"
) else (
    python "%~dp0fish_tracker.py"
)
if errorlevel 1 (
    echo.
    echo Failed to start. Please check Python, NumPy, SciPy and Pillow.
    echo See README.md for installation instructions.
    pause
)
endlocal
