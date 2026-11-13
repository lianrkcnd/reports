@echo off
cd /d "%~dp0"
echo === Committing and pushing all changes ===
git add -A
git commit -m "update reports %date% %time%"
git push
if errorlevel 1 (
  echo.
  echo [X] Push FAILED. Check network or run: git push
  pause
) else (
  echo.
  echo [OK] Pushed to GitHub. Online at: https://lianrkcnd.github.io/reports/
  timeout /t 5 >nul
)
