@echo off
setlocal
cd /d "%~dp0"
title Yasser Social Downloader - Build 1.2.5
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 x64 is required to build the Windows package.
  echo Install Python 3.11 x64, then double-click this file again.
  pause
  exit /b 1
)
py -3.11 -m venv .venv
if errorlevel 1 goto :fail
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :fail
pip install -r requirements.txt
if errorlevel 1 goto :fail
python -m unittest discover -s tests -v
if errorlevel 1 goto :fail
python build.py
if errorlevel 1 goto :fail
echo.
echo DONE: dist\YasserSocialDownloader
pause
exit /b 0
:fail
echo.
echo BUILD FAILED. Review the message above.
pause
exit /b 1
