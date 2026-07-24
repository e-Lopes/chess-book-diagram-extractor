@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1" %*
if errorlevel 1 (
    echo.
    echo O build falhou. Consulte as mensagens acima.
    pause
    exit /b 1
)
echo.
echo Build concluido com sucesso.
