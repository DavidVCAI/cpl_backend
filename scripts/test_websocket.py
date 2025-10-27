"""
Script de prueba para verificar el sistema de WebSocket y sincronización de ubicación

Este script simula múltiples usuarios conectándose y enviando actualizaciones de ubicación.
"""

import asyncio
import websockets
import json
from datetime import datetime
import random

WS_URL = "ws://localhost:8000/ws/"

# Ubicaciones de prueba en Bogotá
BOGOTA_LOCATIONS = [
    {"name": "Plaza de Bolívar", "lng": -74.0721, "lat": 4.5981},
    {"name": "Zona T", "lng": -74.0532, "lat": 4.6659},
    {"name": "Usaquén", "lng": -74.0301, "lat": 4.6976},
    {"name": "Chapinero", "lng": -74.0638, "lat": 4.6314},
    {"name": "Salitre", "lng": -74.0969, "lat": 4.6553},
]


async def simulate_user(user_id: str, location_data: dict):
    """Simula un usuario conectándose y enviando ubicaciones"""
    uri = f"{WS_URL}{user_id}"
    
    try:
        print(f"🔌 [{user_id}] Conectando a {uri}")
        
        async with websockets.connect(uri) as websocket:
            print(f"✅ [{user_id}] Conectado exitosamente")
            
            # Simular movimiento enviando ubicaciones aleatorias cercanas
            for i in range(5):
                # Agregar variación aleatoria a la ubicación
                lat_offset = random.uniform(-0.01, 0.01)
                lng_offset = random.uniform(-0.01, 0.01)
                
                message = {
                    "type": "location_update",
                    "coordinates": [
                        location_data["lng"] + lng_offset,
                        location_data["lat"] + lat_offset
                    ],
                    "accuracy": random.uniform(5, 15),
                    "speed": random.uniform(0, 5),
                    "heading": random.uniform(0, 360),
                    "timestamp": datetime.now().isoformat()
                }
                
                # Enviar ubicación
                await websocket.send(json.dumps(message))
                print(f"📤 [{user_id}] Ubicación enviada: {location_data['name']} (iteración {i+1})")
                
                # Esperar respuesta del servidor
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    data = json.loads(response)
                    print(f"📨 [{user_id}] Respuesta: {data['type']}")
                    
                    if data['type'] == 'nearby_users':
                        print(f"   👥 Usuarios cercanos: {len(data.get('users', []))}")
                    elif data['type'] == 'nearby_events':
                        print(f"   📍 Eventos cercanos: {len(data.get('events', []))}")
                    
                except asyncio.TimeoutError:
                    print(f"⏱️ [{user_id}] Timeout esperando respuesta")
                
                # Esperar antes de la siguiente actualización
                await asyncio.sleep(2)
            
            print(f"✨ [{user_id}] Simulación completada")
            
    except Exception as e:
        print(f"❌ [{user_id}] Error: {e}")


async def main():
    """Ejecuta múltiples simulaciones de usuarios en paralelo"""
    print("🚀 Iniciando simulación de usuarios...")
    print("⚠️  Asegúrate de que el servidor esté corriendo en http://localhost:8000")
    print()
    
    # Crear tareas para múltiples usuarios
    tasks = []
    for i, location in enumerate(BOGOTA_LOCATIONS):
        user_id = f"test-user-{i+1}"
        task = simulate_user(user_id, location)
        tasks.append(task)
    
    # Ejecutar todas las tareas en paralelo
    await asyncio.gather(*tasks)
    
    print()
    print("✅ Simulación completada")
    print("📊 Verifica las ubicaciones en: http://localhost:8000/api/locations")


if __name__ == "__main__":
    print("=" * 60)
    print("  Sistema de Sincronización de Ubicación - Test")
    print("=" * 60)
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Simulación interrumpida por el usuario")
    except Exception as e:
        print(f"\n❌ Error: {e}")

