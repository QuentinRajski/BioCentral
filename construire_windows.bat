@echo off
REM Construit dist\BioCentral.exe (Windows). A lancer sur un PC Windows.
REM Duree : quelques minutes. Resultat : un seul fichier BioCentral.exe a distribuer.
cd /d "%~dp0"
python -m pip install -r requirements.txt -r requirements-build.txt || goto erreur
python -m PyInstaller --noconfirm --clean biocentral.spec || goto erreur
echo.
echo Verification automatique de l'executable (ouvre chaque module puis se ferme)...
set BIOCENTRAL_DATA_DIR=%TEMP%\biocentral_autotest
dist\BioCentral.exe --autotest
if errorlevel 1 goto erreur
echo.
echo Termine : dist\BioCentral.exe
pause
exit /b 0
:erreur
echo.
echo ECHEC de la construction ou de la verification. Voir les messages ci-dessus.
pause
exit /b 1
