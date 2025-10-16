import httpx
from typing import Dict, Optional
from datetime import datetime, timedelta
from app.config import settings


class DailyService:
    """Service for Daily.co video API integration"""

    def __init__(self):
        self.api_key = settings.DAILY_API_KEY
        self.base_url = "https://api.daily.co/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def create_room(
        self,
        room_name: str,
        max_participants: int = 15,
        enable_recording: bool = False
    ) -> Dict:
        """
        Create a new Daily.co video room

        Args:
            room_name: Unique room identifier
            max_participants: Maximum number of participants
            enable_recording: Whether to enable cloud recording

        Returns:
            Room data including URL and name
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/rooms",
                headers=self.headers,
                json={
                    "name": room_name,
                    "properties": {
                        "max_participants": max_participants,
                        "enable_screenshare": True,
                        "enable_chat": True,
                        "enable_recording": "cloud" if enable_recording else "off",
                        "start_video_off": False,
                        "start_audio_off": False,
                        "exp": 3600 * 4  # Room expires in 4 hours
                    }
                }
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "room_name": data["name"],
                    "room_url": data["url"],
                    "created_at": data["created_at"],
                    "config": data["config"]
                }
            else:
                raise Exception(f"Failed to create Daily room: {response.text}")

    async def create_meeting_token(
        self,
        room_name: str,
        user_id: str,
        username: str,
        is_owner: bool = False
    ) -> str:
        """
        Create a meeting token for a specific user

        Args:
            room_name: Daily room name
            user_id: User identifier
            username: Display name in call
            is_owner: Whether user has owner privileges

        Returns:
            Meeting token string
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/meeting-tokens",
                headers=self.headers,
                json={
                    "properties": {
                        "room_name": room_name,
                        "user_name": username,
                        "user_id": user_id,
                        "is_owner": is_owner,
                        "enable_screenshare": True,
                        "enable_recording": is_owner,
                        "start_video_off": False,
                        "start_audio_off": False,
                        "exp": int((datetime.now() + timedelta(hours=4)).timestamp())
                    }
                }
            )

            if response.status_code == 200:
                data = response.json()
                return data["token"]
            else:
                raise Exception(f"Failed to create meeting token: {response.text}")

    async def get_room_info(self, room_name: str) -> Optional[Dict]:
        """Get information about a specific room"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/rooms/{room_name}",
                headers=self.headers
            )

            if response.status_code == 200:
                return response.json()
            else:
                return None

    async def delete_room(self, room_name: str) -> bool:
        """Delete a room when event ends"""
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.base_url}/rooms/{room_name}",
                headers=self.headers
            )

            return response.status_code == 200

    async def get_active_participants(self, room_name: str) -> list:
        """Get list of current participants in a room"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/presence",
                headers=self.headers,
                params={"room": room_name}
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("data", [])
            else:
                return []
