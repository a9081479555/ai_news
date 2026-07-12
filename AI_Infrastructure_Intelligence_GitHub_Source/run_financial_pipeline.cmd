@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=C:\Program Files\Python312\python.exe"

if not exist "%PYTHON%" (
  echo ERROR: Python was not found at %PYTHON%
  echo Update the PYTHON variable in this file if Python is installed elsewhere.
  pause
  exit /b 1
)

echo [1/2] Checking pipeline syntax...
"%PYTHON%" -m py_compile scripts\financial_scoring_pipeline.py
if errorlevel 1 goto :failed

echo [2/2] Downloading MOPS statements and calculating scores...
echo This can take several minutes because requests are rate-limited.
"%PYTHON%" scripts\financial_scoring_pipeline.py --year 114 --season 4
if errorlevel 1 goto :failed

echo.
echo SUCCESS
echo Output files are under data\output
pause
exit /b 0

:failed
echo.
echo FAILED - copy the error message above back to Codex.
pause
exit /b 1
