from fastapi import WebSocket
from typing import Dict, List, Set, Optional, Tuple
import json
import logging
import asyncio
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class UserLocation:
    """User location with metadata for integrity"""
    user_id: str
    coordinates: Tuple[float, float]  # (lng, lat)
    timestamp: datetime
    accuracy: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None


class ConnectionManager:
    """
    Manages WebSocket connections for real-time communication with data consistency guarantees

    Features:
    - Personal messages to specific users
    - Broadcast to all connected users
    - Broadcast to users in specific events
    - Track user locations and active connections
    - Thread-safe operations with asyncio.Lock to prevent race conditions
    - Data integrity for location updates
    """

    def __init__(self):
        # Store active connections: {user_id: WebSocket}
        self.active_connections: Dict[str, WebSocket] = {}

        # Store event participants: {event_id: Set[user_id]}
        self.event_participants: Dict[str, Set[str]] = {}

        # Store user locations with metadata: {user_id: UserLocation}
        self.user_locations: Dict[str, UserLocation] = {}
        
        # Locks for thread-safe operations (prevent race conditions)
        self._connection_lock = asyncio.Lock()
        self._location_lock = asyncio.Lock()
        self._event_lock = asyncio.Lock()
        
        # Location update queue for consistency
        self._location_queue: asyncio.Queue = asyncio.Queue()

    async def connect(self, websocket: WebSocket, user_id: str):
        """Accept WebSocket connection and store it with race condition protection"""
        async with self._connection_lock:
            await websocket.accept()
            self.active_connections[user_id] = websocket
            logger.info(f"✅ User {user_id} connected. Total connections: {len(self.active_connections)}")

    async def disconnect(self, user_id: str):
        """Remove WebSocket connection with race condition protection"""
        async with self._connection_lock:
            if user_id in self.active_connections:
                del self.active_connections[user_id]
                logger.info(f"❌ User {user_id} disconnected. Total connections: {len(self.active_connections)}")

        # Remove from all events
        async with self._event_lock:
            for event_id in list(self.event_participants.keys()):
                if user_id in self.event_participants[event_id]:
                    self.event_participants[event_id].remove(user_id)

                    # Clean up empty event sets
                    if len(self.event_participants[event_id]) == 0:
                        del self.event_participants[event_id]

        # Remove location
        async with self._location_lock:
            if user_id in self.user_locations:
                del self.user_locations[user_id]

    async def send_personal_message(self, user_id: str, message: dict):
        """Send message to a specific user with connection protection"""
        async with self._connection_lock:
            if user_id in self.active_connections:
                try:
                    await self.active_connections[user_id].send_json(message)
                except Exception as e:
                    logger.error(f"Error sending message to {user_id}: {e}")
                    # Don't disconnect here - let the main handler deal with it
                    raise

    async def broadcast(self, message: dict, exclude: List[str] = None):
        """
        Broadcast message to all connected users with connection safety

        Args:
            message: Message to broadcast
            exclude: List of user_ids to exclude from broadcast
        """
        exclude = exclude or []
        disconnected_users = []

        async with self._connection_lock:
            # Create a snapshot of connections to avoid modification during iteration
            connections_snapshot = list(self.active_connections.items())
        
        # Send messages outside the lock to avoid blocking other operations
        for user_id, connection in connections_snapshot:
            if user_id not in exclude:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to {user_id}: {e}")
                    disconnected_users.append(user_id)

        # Clean up disconnected users
        for user_id in disconnected_users:
            await self.disconnect(user_id)

    async def broadcast_to_event(self, event_id: str, message: dict):
        """
        Broadcast message to all participants of a specific event with race condition protection

        Args:
            event_id: Event identifier
            message: Message to broadcast
        """
        async with self._event_lock:
            if event_id not in self.event_participants:
                return
            # Create a snapshot to avoid modification during iteration
            participants = list(self.event_participants[event_id])

        for user_id in participants:
            try:
                await self.send_personal_message(user_id, message)
            except Exception as e:
                logger.error(f"Error sending to {user_id} in event {event_id}: {e}")

    async def join_event(self, user_id: str, event_id: str):
        """Add user to event participants with race condition protection"""
        async with self._event_lock:
            if event_id not in self.event_participants:
                self.event_participants[event_id] = set()

            self.event_participants[event_id].add(user_id)
            logger.info(f"User {user_id} joined event {event_id}")

    async def leave_event(self, user_id: str, event_id: str):
        """Remove user from event participants with race condition protection"""
        async with self._event_lock:
            if event_id in self.event_participants:
                self.event_participants[event_id].discard(user_id)

                # Clean up empty event sets
                if len(self.event_participants[event_id]) == 0:
                    del self.event_participants[event_id]

                logger.info(f"User {user_id} left event {event_id}")

    async def update_user_location(
        self, 
        user_id: str, 
        coordinates: Tuple[float, float],
        accuracy: Optional[float] = None,
        speed: Optional[float] = None,
        heading: Optional[float] = None
    ) -> UserLocation:
        """
        Update user's location with full data integrity and race condition protection
        
        Args:
            user_id: User identifier
            coordinates: (longitude, latitude)
            accuracy: GPS accuracy in meters
            speed: Speed in m/s
            heading: Heading in degrees (0-360)
            
        Returns:
            UserLocation object with updated data
        """
        async with self._location_lock:
            location = UserLocation(
                user_id=user_id,
                coordinates=coordinates,
                timestamp=datetime.now(),
                accuracy=accuracy,
                speed=speed,
                heading=heading
            )
            
            # Only update if this is newer than existing location
            if user_id in self.user_locations:
                old_location = self.user_locations[user_id]
                if old_location.timestamp > location.timestamp:
                    logger.warning(f"Rejecting old location update for {user_id}")
                    return old_location
            
            self.user_locations[user_id] = location
            logger.debug(f"Updated location for {user_id}: {coordinates}")
            return location
    
    async def get_user_location(self, user_id: str) -> Optional[UserLocation]:
        """Get user's current location with race condition protection"""
        async with self._location_lock:
            return self.user_locations.get(user_id)
    
    async def get_all_locations(self) -> Dict[str, UserLocation]:
        """Get all user locations with race condition protection"""
        async with self._location_lock:
            return dict(self.user_locations)

    async def get_event_participants(self, event_id: str) -> List[str]:
        """Get list of user IDs in an event with race condition protection"""
        async with self._event_lock:
            return list(self.event_participants.get(event_id, set()))

    async def get_nearby_users(self, coordinates: Tuple[float, float], radius_km: float = 5.0) -> List[dict]:
        """
        Get users within a certain radius with race condition protection

        Args:
            coordinates: (lng, lat)
            radius_km: Radius in kilometers

        Returns:
            List of {user_id, coordinates, distance, timestamp}
        """
        from geopy.distance import geodesic

        nearby_users = []
        user_point = (coordinates[1], coordinates[0])  # (lat, lng) for geodesic

        async with self._location_lock:
            # Create snapshot to avoid holding lock during calculations
            locations_snapshot = dict(self.user_locations)
        
        for user_id, user_location in locations_snapshot.items():
            other_point = (user_location.coordinates[1], user_location.coordinates[0])
            distance = geodesic(user_point, other_point).kilometers

            if distance <= radius_km:
                nearby_users.append({
                    "user_id": user_id,
                    "coordinates": list(user_location.coordinates),
                    "distance": round(distance, 2),
                    "timestamp": user_location.timestamp.isoformat(),
                    "accuracy": user_location.accuracy,
                    "speed": user_location.speed,
                    "heading": user_location.heading
                })

        # Sort by distance
        nearby_users.sort(key=lambda x: x["distance"])
        return nearby_users

    async def get_stats(self) -> dict:
        """Get connection statistics with race condition protection"""
        async with self._connection_lock:
            total_connections = len(self.active_connections)
        
        async with self._event_lock:
            active_events = len(self.event_participants)
            total_participants = sum(len(participants) for participants in self.event_participants.values())
        
        async with self._location_lock:
            users_with_location = len(self.user_locations)
        
        return {
            "total_connections": total_connections,
            "active_events": active_events,
            "total_participants": total_participants,
            "users_with_location": users_with_location
        }
    
    async def broadcast_location_update(self, user_id: str, location: UserLocation, exclude_user: bool = True):
        """
        Broadcast a user's location update to all connected users
        
        Args:
            user_id: User whose location was updated
            location: UserLocation object
            exclude_user: Whether to exclude the user from the broadcast
        """
        message = {
            "type": "location_update",
            "user_id": user_id,
            "coordinates": list(location.coordinates),
            "timestamp": location.timestamp.isoformat(),
            "accuracy": location.accuracy,
            "speed": location.speed,
            "heading": location.heading
        }
        
        exclude_list = [user_id] if exclude_user else []
        await self.broadcast(message, exclude=exclude_list)
