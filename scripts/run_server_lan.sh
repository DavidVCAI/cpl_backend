#!/bin/bash
# Script para ejecutar el backend en la red local (LAN)
# Para Linux/macOS

echo "========================================"
echo "  CityPulse Live - Backend Server"
echo "  Modo: Red Local (LAN)"
echo "========================================"
echo ""

# Obtener IP local
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    IP=$(ipconfig getifaddr en0)
else
    # Linux
    IP=$(hostname -I | awk '{print $1}')
fi

echo "IP Local detectada: $IP"
echo ""

echo "Iniciando servidor FastAPI..."
echo "Backend estará disponible en:"
echo "  - Local:   http://localhost:8000"
echo "  - Red LAN: http://$IP:8000"
echo "  - Docs:    http://$IP:8000/docs"
echo "  - WebSocket: ws://$IP:8000/ws/user_id"
echo ""
echo "Presiona Ctrl+C para detener el servidor"
echo ""

# Ejecutar servidor con host 0.0.0.0 para aceptar conexiones externas
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
