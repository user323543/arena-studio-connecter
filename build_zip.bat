@echo off
rem ===========================================================================
rem  Baut das Release-ZIP (dist\ArenaStudioConnector-v<Version>.zip)
rem  Voraussetzung: Python 3 (nur zum Bauen - die App selbst braucht kein
rem  PyInstaller mehr, es wird schlicht ein ZIP gepackt).
rem ===========================================================================
chcp 65001 >nul 2>&1
setlocal EnableExtensions
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [X] Python 3 wird zum Bauen des ZIP benoetigt.
    echo     Download: https://www.python.org/downloads/windows/
    echo.
    pause
    endlocal
    exit /b 1
)

python build_zip.py %*
set "RC=%errorlevel%"
echo.
if not "%RC%"=="0" (
    echo [X] Bau fehlgeschlagen - Meldung siehe oben.
) else (
    echo [OK] Fertig. Das ZIP liegt im Ordner "dist".
)
echo.
pause
endlocal
exit /b %RC%
