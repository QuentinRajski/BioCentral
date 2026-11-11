@echo off
REM Lance BioCentral v2 depuis ce dossier (Python et les dependances doivent etre installes).
cd /d "%~dp0"
python main.py
if errorlevel 1 pause
