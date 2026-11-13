@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo === [1/3] Commit all changes ===
git add -A
git commit -m "update reports %date% %time%" >nul 2>&1
if errorlevel 1 echo     nothing new to commit
echo === [2/3] Sync with remote ===
git pull --rebase >nul 2>&1
echo === [3/3] Push to GitHub (up to 5 attempts) ===
set OK=0
for /L %%i in (1,1,5) do (
  if !OK!==0 git push >nul 2>&1 && set OK=1
  if !OK!==0 (
    echo     attempt %%i failed, retrying in 5s...
    timeout /t 5 /nobreak >nul
  )
)
if !OK!==1 (
  echo.
  echo [OK] Pushed. Online at: https://lianrkcnd.github.io/reports/
  echo     (this window closes in 8s)
  timeout /t 8 >nul
) else (
  echo.
  echo [X] All 5 attempts failed - network to github.com is down right now.
  echo     Your changes are saved locally and are NOT lost.
  echo     Try again in a few minutes, or turn on your VPN/proxy first.
  pause
)
