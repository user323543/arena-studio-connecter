@echo off
REM Baut die ArenaStudioConnector.exe (einmalig Python 3.11+ von python.org installieren)
chcp 65001 >nul
cd /d "%~dp0"
echo [1/3] PyInstaller installieren...
python -m pip install --upgrade pyinstaller
echo [2/3] EXE bauen...
python -m PyInstaller --noconfirm ArenaStudioConnector.spec
echo [3/3] Fertig: dist\ArenaStudioConnector.exe
echo Kopiere danach .env.example als .env daneben und trage deinen Roblox-Key ein.
pause
