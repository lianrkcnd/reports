@echo off
REM Usage: add-report.bat "C:\path\to\report.html" [daily|weekly]
REM        second argument optional, default = daily
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: add-report.bat "report-file" [daily^|weekly]
  pause
  exit /b 1
)
set dest=daily
if /i "%~2"=="weekly" set dest=weekly
echo === Copying "%~nx1" into %dest%/ ===
copy /y "%~1" "%dest%\%~nx1"
git add -A
git commit -m "add %dest% report: %~nx1"
git push
if errorlevel 1 (
  echo.
  echo [X] Push FAILED. Check network or run: git push
  pause
) else (
  echo.
  echo [OK] Online at: https://lianrkcnd.github.io/reports/%dest%/%~nx1
  timeout /t 5 >nul
)
