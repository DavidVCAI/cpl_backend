@echo off
REM Script para ejecutar el backend en la red local (LAN)
REM Asegurate de tener Python y las dependencias instaladas

echo ========================================
echo   CityPulse Live - Backend Server
echo   Modo: Red Local (LAN)
echo ========================================
echo.

REM Obtener IP local
echo Detectando IP local...
for /f "tokens=2 delimiters=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    set IP=%%a
    goto :found
)
:found
set IP=%IP:~1%
echo IP Local detectada: %IP%
echo.

echo Iniciando servidor FastAPI...
echo Backend estara disponible en:
echo   - Local:   http://localhost:8000
echo   - Red LAN: http://%IP%:8000
echo   - Docs:    http://%IP%:8000/docs
echo   - WebSocket: ws://%IP%:8000/ws/user_id
echo.
echo Presiona Ctrl+C para detener el servidor
echo.

REM Ejecutar servidor con host 0.0.0.0 para aceptar conexiones externas
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
