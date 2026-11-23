@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set "PY=py -3"
where py >nul 2>nul || set "PY=python"
%PY% -c "import PIL" >nul 2>nul || %PY% -m pip install --quiet pillow
%PY% run_student.py %*
if errorlevel 1 pause
