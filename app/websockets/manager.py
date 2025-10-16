from fastapi import WebSocket
from typing import Dict, List, Set
import json
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections for real-time communication

    Features:
    - Personal messages to specific users
    - Broadcast to all connected users
    - Broadcast to users in specific events
    - Track user locations and active connections
    """

    def __init__(self):
        # Store active connections: {user_id: WebSocket}
        self.active_connections: Dict[str, WebSocket] = {}

        # Store event participants: {event_id: Set[user_id]}
        self.event_participants: Dict[str, Set[str]] = {}

        # Store user locations: {user_id: [lng, lat]}
        self.user_locations: Dict[str, List[float]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        """Accept WebSocket connection and store it"""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(f"✅ User {user_id} connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, user_id: str):
        """Remove WebSocket connection"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            logger.info(f"❌ User {user_id} disconnected. Total connections: {len(self.active_connections)}")

        # Remove from all events
        for event_id in list(self.event_participants.keys()):
            if user_id in self.event_participants[event_id]:
                self.event_participants[event_id].remove(user_id)

                # Clean up empty event sets
                if len(self.event_participants[event_id]) == 0:
                    del self.event_participants[event_id]

        # Remove location
        if user_id in self.user_locations:
            del self.user_locations[user_id]

    async def send_personal_message(self, user_id: str, message: dict):
        """Send message to a specific user"""
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to {user_id}: {e}")
                self.disconnect(user_id)

    async def broadcast(self, message: dict, exclude: List[str] = None):
        """
        Broadcast message to all connected users

        Args:
            message: Message to broadcast
            exclude: List of user_ids to exclude from broadcast
        """
        exclude = exclude or []

        disconnected_users = []

        for user_id, connection in self.active_connections.items():
            if user_id not in exclude:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to {user_id}: {e}")
                    disconnected_users.append(user_id)

        # Clean up disconnected users
        for user_id in disconnected_users:
            self.disconnect(user_id)

    async def broadcast_to_event(self, event_id: str, message: dict):
        """
        Broadcast message to all participants of a specific event

        Args:
            event_id: Event identifier
            message: Message to broadcast
        """
        if event_id not in self.event_participants:
            return

        participants = self.event_participants[event_id].copy()

        for user_id in participants:
            await self.send_personal_message(user_id, message)

    def join_event(self, user_id: str, event_id: str):
        """Add user to event participants"""
        if event_id not in self.event_participants:
            self.event_participants[event_id] = set()

        self.event_participants[event_id].add(user_id)
        logger.info(f"User {user_id} joined event {event_id}")

    def leave_event(self, user_id: str, event_id: str):
        """Remove user from event participants"""
        if event_id in self.event_participants:
            self.event_participants[event_id].discard(user_id)

            # Clean up empty event sets
            if len(self.event_participants[event_id]) == 0:
                del self.event_participants[event_id]

            logger.info(f"User {user_id} left event {event_id}")

    def update_user_location(self, user_id: str, coordinates: List[float]):
        """Update user's location"""
        self.user_locations[user_id] = coordinates

    def get_event_participants(self, event_id: str) -> List[str]:
        """Get list of user IDs in an event"""
        return list(self.event_participants.get(event_id, set()))

    def get_nearby_users(self, coordinates: List[float], radius_km: float = 5.0) -> List[dict]:
        """
        Get users within a certain radius

        Args:
            coordinates: [lng, lat]
            radius_km: Radius in kilometers

        Returns:
            List of {user_id, coordinates, distance}
        """
        from geopy.distance import geodesic

        nearby_users = []
        user_point = (coordinates[1], coordinates[0])  # (lat, lng)

        for user_id, user_coords in self.user_locations.items():
            other_point = (user_coords[1], user_coords[0])
            distance = geodesic(user_point, other_point).kilometers

            if distance <= radius_km:
                nearby_users.append({
                    "user_id": user_id,
                    "coordinates": user_coords,
                    "distance": round(distance, 2)
                })

        # Sort by distance
        nearby_users.sort(key=lambda x: x["distance"])

        return nearby_users

    def get_stats(self) -> dict:
        """Get connection statistics"""
        return {
            "total_connections": len(self.active_connections),
            "active_events": len(self.event_participants),
            "total_participants": sum(len(participants) for participants in self.event_participants.values()),
            "users_with_location": len(self.user_locations)
        }
