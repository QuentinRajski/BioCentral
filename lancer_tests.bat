@echo off
REM Lance la suite de tests automatiques de BioCentral.
cd /d "%~dp0"
set QT_QPA_PLATFORM=offscreen
python -m unittest discover -s tests -t . -v
pause
